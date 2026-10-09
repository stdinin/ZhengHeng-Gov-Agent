import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import httpx
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
from backend.app.ingestion.indexer import DocumentIndexer
from backend.app.main import create_app
from backend.app.retrieval.bm25 import OpenSearchBM25
from backend.app.retrieval.dense import MilvusDenseIndex
from backend.app.storage.document_repository import MongoDocumentRepository


class FixedIntegrationEmbedder:
    """Deterministic vectors; the repositories and index services remain real."""

    async def embed(self, text: str) -> list[float]:
        assert text
        return [1.0, 0.0, 0.0, 0.0]


@pytest.mark.integration
async def test_real_document_indexer_promotes_parsed_version_to_ready_and_indexes_chunks() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1.")

    suffix = uuid4().hex
    settings = Settings(
        mongo_uri="mongodb://localhost:27017",
        mongo_db=f"zhengheng_indexer_it_{suffix}",
        opensearch_url="http://localhost:9201",
        milvus_host="localhost",
    )
    repository = MongoDocumentRepository(settings)
    sparse = OpenSearchBM25(settings, index_name=f"policy_chunks_indexer_it_{suffix}")
    dense = MilvusDenseIndex(
        settings,
        embedding_dim=4,
        embedding_model="integration-fixture-vector-v1",
        collection_name=f"policy_chunks_indexer_it_{suffix}",
    )
    indexer = DocumentIndexer(
        repository=repository,
        sparse=sparse,
        dense=dense,
        embedder=FixedIntegrationEmbedder(),
    )
    now = datetime.now(UTC)
    document = Document(
        id=f"doc_indexer_{suffix}",
        logical_name="真实索引演示政策",
        department_id="dept_tax",
        source_type=SourceType.DATASET,
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=f"ver_indexer_{suffix}",
        document_id=document.id,
        version_no=1,
        sha256=sha256(suffix.encode()).hexdigest(),
        status=DocumentVersionStatus.PARSED,
        policy_status=PolicyStatus.FULLY_EFFECTIVE,
        title=document.logical_name,
        raw_text="小规模纳税人可以适用增值税优惠政策。",
        trace_id=f"trace_indexer_{suffix}",
        created_at=now,
        updated_at=now,
    )
    chunk = Chunk(
        id=f"chunk_indexer_{suffix}",
        document_id=document.id,
        version_id=version.id,
        ordinal=1,
        text=version.raw_text,
        trace_id=version.trace_id,
        created_at=now,
        updated_at=now,
    )
    try:
        await repository.initialize_indexes()
        await repository.create_document(document)
        await repository.create_version(version)
        await repository.create_chunks([chunk])

        indexed = await indexer.index_version(version.id)

        assert indexed.status is DocumentVersionStatus.READY
        assert indexed.indexed_at is not None
        assert [item.chunk_id for item in await sparse.search("小规模纳税人增值税优惠")] == [
            chunk.id
        ]
        assert [
            item.chunk_id
            for item in await dense.search([1.0, 0.0, 0.0, 0.0], department_ids=["dept_tax"])
        ] == [chunk.id]
    finally:
        await dense.drop_collection()
        await sparse.delete_index()
        await sparse.close()
        await repository.close()


@pytest.mark.integration
async def test_real_document_reindex_api_uses_all_three_persistence_planes() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1.")

    suffix = uuid4().hex
    settings = Settings(
        mongo_uri="mongodb://localhost:27017",
        mongo_db=f"zhengheng_reindex_api_it_{suffix}",
        opensearch_url="http://localhost:9201",
        milvus_host="localhost",
    )
    repository = MongoDocumentRepository(settings)
    sparse = OpenSearchBM25(settings, index_name=f"policy_chunks_reindex_api_it_{suffix}")
    dense = MilvusDenseIndex(
        settings,
        embedding_dim=4,
        embedding_model="integration-fixture-vector-v1",
        collection_name=f"policy_chunks_reindex_api_it_{suffix}",
    )
    indexer = DocumentIndexer(
        repository=repository,
        sparse=sparse,
        dense=dense,
        embedder=FixedIntegrationEmbedder(),
    )
    now = datetime.now(UTC)
    document = Document(
        id=f"doc_reindex_api_{suffix}",
        logical_name="重建索引演示政策",
        department_id="dept_tax",
        source_type=SourceType.UPLOAD,
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=f"ver_reindex_api_{suffix}",
        document_id=document.id,
        version_no=1,
        sha256=sha256(f"api:{suffix}".encode()).hexdigest(),
        status=DocumentVersionStatus.PARSED,
        policy_status=PolicyStatus.FULLY_EFFECTIVE,
        title=document.logical_name,
        raw_text="政策文档已经通过真实索引 API 写入三个持久化平面。",
        trace_id=f"trace_reindex_api_{suffix}",
        created_at=now,
        updated_at=now,
    )
    chunk = Chunk(
        id=f"chunk_reindex_api_{suffix}",
        document_id=document.id,
        version_id=version.id,
        ordinal=1,
        text=version.raw_text,
        trace_id=version.trace_id,
        created_at=now,
        updated_at=now,
    )
    try:
        await repository.initialize_indexes()
        await repository.create_document(document)
        await repository.create_version(version)
        await repository.create_chunks([chunk])
        app = create_app(settings=settings, document_repository=repository)
        app.state.document_indexer = indexer
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(f"/api/v1/documents/versions/{version.id}/reindex")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == DocumentVersionStatus.READY
        assert await sparse.count_version_records(version.id) == 1
        assert await dense.count_version_records(version.id) == 1
    finally:
        await dense.drop_collection()
        await sparse.delete_index()
        await sparse.close()
        await repository.close()
