import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from backend.app.config import Settings
from backend.app.domain.documents import (
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    PolicyStatus,
    SourceType,
)
from backend.app.retrieval.bm25 import BM25ChunkRecord, OpenSearchBM25
from backend.app.retrieval.dense import DenseVectorRecord, MilvusDenseIndex
from backend.app.retrieval.hybrid import HybridEvidenceRetriever
from backend.app.retrieval.reranker import CrossEncoderReranker
from backend.app.retrieval.rrf import RankedCandidate
from backend.app.storage.document_repository import MongoDocumentRepository

_INFRA_SKIP = "SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1 after Compose is healthy."


def _settings() -> Settings:
    return Settings(
        mongo_uri="mongodb://localhost:27017",
        mongo_db="zhengheng_retrieval_integration",
        redis_url="redis://localhost:6379/0",
        opensearch_url="http://localhost:9201",
        milvus_host="localhost",
    )


def _require_infrastructure() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip(_INFRA_SKIP)


async def _cleanup_document_graph(repository: MongoDocumentRepository, document_id: str) -> None:
    await repository._chunks.delete_many({"document_id": document_id})
    await repository._versions.delete_many({"document_id": document_id})
    await repository._documents.delete_one({"_id": document_id})


@pytest.mark.integration
async def test_real_opensearch_bm25_filters_archived_policy_chunks() -> None:
    _require_infrastructure()
    suffix = uuid4().hex
    backend = OpenSearchBM25(_settings(), index_name=f"policy_chunks_bm25_it_{suffix}")
    try:
        await backend.initialize()
        await backend.index_records(
            [
                BM25ChunkRecord(
                    chunk_id=f"chunk_active_{suffix}",
                    document_id=f"doc_{suffix}",
                    version_id=f"ver_active_{suffix}",
                    department_id="dept_tax",
                    title="增值税优惠公告",
                    text="小规模纳税人适用增值税优惠。",
                ),
                BM25ChunkRecord(
                    chunk_id=f"chunk_archived_{suffix}",
                    document_id=f"doc_{suffix}",
                    version_id=f"ver_archived_{suffix}",
                    department_id="dept_tax",
                    title="已归档增值税公告",
                    text="历史增值税优惠。",
                    active=False,
                    version_status=DocumentVersionStatus.ARCHIVED,
                ),
            ]
        )

        results = await backend.search("小规模纳税人增值税优惠", department_ids=["dept_tax"])

        assert [item.chunk_id for item in results] == [f"chunk_active_{suffix}"]
    finally:
        await backend.delete_index()
        await backend.close()


@pytest.mark.integration
async def test_real_milvus_filters_archived_policy_chunks() -> None:
    _require_infrastructure()
    suffix = uuid4().hex
    backend = MilvusDenseIndex(
        _settings(),
        embedding_dim=4,
        embedding_model="integration-fixture-vector-v1",
        collection_name=f"policy_chunks_dense_it_{suffix}",
    )
    try:
        await backend.initialize()
        await backend.upsert(
            [
                DenseVectorRecord(
                    chunk_id=f"chunk_active_{suffix}",
                    document_id=f"doc_{suffix}",
                    version_id=f"ver_active_{suffix}",
                    department_id="dept_tax",
                    embedding=[1.0, 0.0, 0.0, 0.0],
                ),
                DenseVectorRecord(
                    chunk_id=f"chunk_archived_{suffix}",
                    document_id=f"doc_{suffix}",
                    version_id=f"ver_archived_{suffix}",
                    department_id="dept_tax",
                    embedding=[0.0, 1.0, 0.0, 0.0],
                    active=False,
                    version_status=DocumentVersionStatus.ARCHIVED,
                ),
            ]
        )

        results = await backend.search([1.0, 0.0, 0.0, 0.0], department_ids=["dept_tax"])

        assert [item.chunk_id for item in results] == [f"chunk_active_{suffix}"]
    finally:
        await backend.drop_collection()


@pytest.mark.integration
async def test_real_mongo_canonical_recheck_requires_active_current_version_pointer() -> None:
    _require_infrastructure()
    suffix = uuid4().hex
    now = datetime.now(UTC)
    repository = MongoDocumentRepository(_settings())
    document_id = f"doc_{suffix}"
    try:
        await repository.initialize_indexes()
        version = DocumentVersion(
            id=f"ver_{suffix}",
            document_id=document_id,
            version_no=1,
            sha256=sha256(f"canonical:{suffix}".encode()).hexdigest(),
            status=DocumentVersionStatus.ACTIVE,
            policy_status=PolicyStatus.FULLY_EFFECTIVE,
            title="增值税优惠公告",
            document_number="示例〔2026〕1号",
            raw_text="小规模纳税人适用增值税优惠。",
            trace_id=f"trace_{suffix}",
            created_at=now,
            updated_at=now,
        )
        document = Document(
            id=document_id,
            logical_name="增值税优惠公告",
            department_id="dept_tax",
            source_type=SourceType.DATASET,
            source_url="https://example.invalid/policy",
            current_active_version_id=version.id,
            created_at=now,
            updated_at=now,
        )
        active_chunk = Chunk(
            id=f"chunk_active_{suffix}",
            document_id=document.id,
            version_id=version.id,
            ordinal=1,
            text="小规模纳税人适用增值税优惠。",
            trace_id=f"trace_{suffix}",
            created_at=now,
            updated_at=now,
        )
        archived_chunk = active_chunk.model_copy(
            update={"id": f"chunk_archived_{suffix}", "version_id": f"old_{suffix}"}
        )
        archived_version = version.model_copy(
            update={
                "id": archived_chunk.version_id,
                "version_no": 2,
                "status": DocumentVersionStatus.ARCHIVED,
                "sha256": sha256(f"canonical-archived:{suffix}".encode()).hexdigest(),
            }
        )
        await repository.create_document(document)
        await repository.create_version(version)
        await repository.create_version(archived_version)
        await repository.create_chunks([active_chunk, archived_chunk])
        candidates = [
            RankedCandidate(active_chunk.id, document.id, version.id, 1),
            RankedCandidate(archived_chunk.id, document.id, archived_version.id, 2),
        ]

        rerank_evidence = await repository.get_evidence_for_rerank(candidates)
        canonical = await repository.get_canonical_evidence(candidates)

        assert [item.chunk_id for item in rerank_evidence] == [active_chunk.id, archived_chunk.id]
        assert [item.chunk_id for item in canonical] == [active_chunk.id]
        assert canonical[0].source_url == document.source_url
    finally:
        await _cleanup_document_graph(repository, document_id)
        await repository.close()


class FixedIntegrationEmbedder:
    """A fixed test query vector; Mongo/OpenSearch/Milvus remain real services."""

    async def embed(self, query: str) -> list[float]:
        assert query
        return [1.0, 0.0, 0.0, 0.0]


@pytest.mark.integration
async def test_real_hybrid_retriever_excludes_an_archived_stale_index_candidate() -> None:
    """The archived identity exists in both indexes but cannot survive Mongo canonical re-check."""

    _require_infrastructure()
    suffix = uuid4().hex
    now = datetime.now(UTC)
    settings = _settings()
    repository = MongoDocumentRepository(settings)
    document_id = f"doc_hybrid_{suffix}"
    sparse = OpenSearchBM25(settings, index_name=f"policy_chunks_hybrid_it_{suffix}")
    dense = MilvusDenseIndex(
        settings,
        embedding_dim=4,
        embedding_model="integration-fixture-vector-v1",
        collection_name=f"policy_chunks_hybrid_it_{suffix}",
    )
    try:
        await repository.initialize_indexes()
        active_version = DocumentVersion(
            id=f"ver_hybrid_active_{suffix}",
            document_id=document_id,
            version_no=1,
            sha256=sha256(f"hybrid-active:{suffix}".encode()).hexdigest(),
            status=DocumentVersionStatus.ACTIVE,
            policy_status=PolicyStatus.FULLY_EFFECTIVE,
            title="小规模纳税人增值税优惠",
            raw_text="小规模纳税人适用增值税优惠。",
            trace_id=f"trace_hybrid_{suffix}",
            created_at=now,
            updated_at=now,
        )
        document = Document(
            id=document_id,
            logical_name=active_version.title,
            department_id="dept_tax",
            source_type=SourceType.DATASET,
            current_active_version_id=active_version.id,
            created_at=now,
            updated_at=now,
        )
        active_chunk = Chunk(
            id=f"chunk_hybrid_active_{suffix}",
            document_id=document.id,
            version_id=active_version.id,
            ordinal=1,
            text="小规模纳税人适用增值税优惠。",
            trace_id=f"trace_hybrid_{suffix}",
            created_at=now,
            updated_at=now,
        )
        archived_version = active_version.model_copy(
            update={
                "id": f"ver_hybrid_archived_{suffix}",
                "version_no": 2,
                "sha256": sha256(f"hybrid-archived:{suffix}".encode()).hexdigest(),
                "status": DocumentVersionStatus.ARCHIVED,
            }
        )
        archived_chunk = active_chunk.model_copy(
            update={
                "id": f"chunk_hybrid_archived_{suffix}",
                "version_id": archived_version.id,
                "ordinal": 2,
                "text": "已归档的历史增值税优惠。",
            }
        )
        await repository.create_document(document)
        await repository.create_version(active_version)
        await repository.create_version(archived_version)
        await repository.create_chunks([active_chunk, archived_chunk])
        await sparse.initialize()
        await dense.initialize()
        # Deliberately retain stale ACTIVE lifecycle fields in both search indexes.
        # Only the Mongo fact plane is authoritative for archival/current-pointer status.
        await sparse.index_records(
            [
                BM25ChunkRecord(
                    chunk_id=active_chunk.id,
                    document_id=document.id,
                    version_id=active_version.id,
                    department_id=document.department_id,
                    title=active_version.title,
                    text=active_chunk.text,
                ),
                BM25ChunkRecord(
                    chunk_id=archived_chunk.id,
                    document_id=document.id,
                    version_id=archived_version.id,
                    department_id=document.department_id,
                    title="历史增值税优惠",
                    text=archived_chunk.text,
                    active=True,
                    version_status=DocumentVersionStatus.ACTIVE,
                ),
            ]
        )
        await dense.upsert(
            [
                DenseVectorRecord(
                    chunk_id=active_chunk.id,
                    document_id=document.id,
                    version_id=active_version.id,
                    department_id=document.department_id,
                    embedding=[0.9, 0.1, 0.0, 0.0],
                ),
                DenseVectorRecord(
                    chunk_id=archived_chunk.id,
                    document_id=document.id,
                    version_id=archived_version.id,
                    department_id=document.department_id,
                    embedding=[1.0, 0.0, 0.0, 0.0],
                    active=True,
                    version_status=DocumentVersionStatus.ACTIVE,
                ),
            ]
        )
        retriever = HybridEvidenceRetriever(
            bm25=sparse,
            dense=dense,
            embedder=FixedIntegrationEmbedder(),
            canonical_store=repository,
            reranker=CrossEncoderReranker(model_name=settings.reranker_model),
            reranker_enabled=True,
        )

        result = await retriever.retrieve_with_trace(
            queries=["小规模纳税人增值税优惠"],
            department_ids=[document.department_id],
            limit=8,
        )

        assert [item.chunk_id for item in result.evidence] == [active_chunk.id]
        assert result.trace.reranker_skipped is False
        assert result.trace.reranked_candidate_count == 2
        assert result.trace.canonical_candidate_count == 1
    finally:
        await dense.drop_collection()
        await sparse.delete_index()
        await sparse.close()
        await _cleanup_document_graph(repository, document_id)
        await repository.close()
