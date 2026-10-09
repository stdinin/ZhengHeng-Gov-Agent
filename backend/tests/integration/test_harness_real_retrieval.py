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
from backend.app.harness.chat_service import HarnessChatService
from backend.app.harness.composition import _DEPARTMENT_RULES
from backend.app.harness.nodes import (
    AnswerNode,
    FixedDagNodes,
    IntentNode,
    RetrieveNode,
    RewriteNode,
    RouteNode,
    VerifyNode,
)
from backend.app.harness.policy import PolicyHarness
from backend.app.llm.fake import FakeLLM
from backend.app.main import create_app
from backend.app.retrieval.bm25 import BM25ChunkRecord, OpenSearchBM25
from backend.app.retrieval.dense import DenseVectorRecord, MilvusDenseIndex
from backend.app.retrieval.hybrid import HybridEvidenceRetriever
from backend.app.retrieval.reranker import CrossEncoderReranker
from backend.app.security.auth import User, create_access_token, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.document_repository import MongoDocumentRepository
from backend.app.storage.trace_repository import MongoTraceStore
from backend.app.storage.users import InMemoryUserStore


class FixedIntegrationEmbedder:
    async def embed(self, query: str) -> list[float]:
        assert query
        return [1.0, 0.0, 0.0, 0.0]


async def _cleanup(repository: MongoDocumentRepository, document_id: str) -> None:
    await repository._chunks.delete_many({"document_id": document_id})
    await repository._versions.delete_many({"document_id": document_id})
    await repository._documents.delete_one({"_id": document_id})


@pytest.mark.integration
async def test_it01_it03_real_chat_api_cites_only_active_policy_and_persists_trace() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1.")

    suffix = uuid4().hex
    settings = Settings(
        app_secret="test-secret-that-is-at-least-32-bytes",
        mongo_uri="mongodb://localhost:27017",
        mongo_db=f"zhengheng_harness_it_{suffix}",
        opensearch_url="http://localhost:9201",
        milvus_host="localhost",
        reranker_enabled=True,
    )
    repository = MongoDocumentRepository(settings)
    sparse = OpenSearchBM25(settings, index_name=f"policy_chunks_harness_it_{suffix}")
    dense = MilvusDenseIndex(
        settings,
        embedding_dim=4,
        embedding_model="integration-fixture-vector-v1",
        collection_name=f"policy_chunks_harness_it_{suffix}",
    )
    trace_store = MongoTraceStore(settings)
    document_id = f"doc_harness_{suffix}"
    now = datetime.now(UTC)
    active_version = DocumentVersion(
        id=f"ver_harness_active_{suffix}",
        document_id=document_id,
        version_no=1,
        sha256=sha256(f"active:{suffix}".encode()).hexdigest(),
        status=DocumentVersionStatus.ACTIVE,
        policy_status=PolicyStatus.FULLY_EFFECTIVE,
        title="小规模纳税人增值税优惠公告",
        raw_text="符合条件的小规模纳税人可以适用增值税优惠。",
        trace_id=f"trace_seed_{suffix}",
        created_at=now,
        updated_at=now,
    )
    archived_version = active_version.model_copy(
        update={
            "id": f"ver_harness_archived_{suffix}",
            "version_no": 2,
            "sha256": sha256(f"archived:{suffix}".encode()).hexdigest(),
            "status": DocumentVersionStatus.ARCHIVED,
            "raw_text": "这是一条已经归档的历史优惠政策。",
        }
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
        id=f"chunk_harness_active_{suffix}",
        document_id=document.id,
        version_id=active_version.id,
        ordinal=1,
        text=active_version.raw_text,
        trace_id=active_version.trace_id,
        created_at=now,
        updated_at=now,
    )
    archived_chunk = active_chunk.model_copy(
        update={
            "id": f"chunk_harness_archived_{suffix}",
            "version_id": archived_version.id,
            "ordinal": 2,
            "text": archived_version.raw_text,
        }
    )
    llm = FakeLLM(
        structured_fixtures={
            "intent": {"intent": "POLICY_QUERY", "confidence": 1.0},
            "rewrite": {"queries": ["小规模纳税人增值税优惠"]},
            "route": {"routes": [{"department_id": "dept_tax", "score": 1.0}]},
            "answer": {
                "answer": "符合条件的小规模纳税人可以适用增值税优惠。",
                "claims": [
                    {
                        "text": "符合条件的小规模纳税人可以适用增值税优惠。",
                        "citation_ids": ["C1"],
                    }
                ],
            },
            "verify_claim": {
                "supported": True,
                "support_score": 1.0,
                "contradiction": False,
                "reason": "原文直接支持该限定性结论。",
            },
        }
    )
    try:
        await repository.initialize_indexes()
        await repository.create_document(document)
        await repository.create_version(active_version)
        await repository.create_version(archived_version)
        await repository.create_chunks([active_chunk, archived_chunk])
        await sparse.initialize()
        await dense.initialize()
        # The archived version intentionally remains stale/ACTIVE in both search
        # planes.  Mongo's canonical re-check is what must reject it.
        await sparse.index_records(
            [
                BM25ChunkRecord(
                    chunk_id=active_chunk.id,
                    document_id=document.id,
                    version_id=active_version.id,
                    department_id="dept_tax",
                    title=active_version.title,
                    text=active_chunk.text,
                ),
                BM25ChunkRecord(
                    chunk_id=archived_chunk.id,
                    document_id=document.id,
                    version_id=archived_version.id,
                    department_id="dept_tax",
                    title="历史优惠政策",
                    text=archived_chunk.text,
                ),
            ]
        )
        await dense.upsert(
            [
                DenseVectorRecord(
                    chunk_id=active_chunk.id,
                    document_id=document.id,
                    version_id=active_version.id,
                    department_id="dept_tax",
                    embedding=[0.9, 0.1, 0.0, 0.0],
                ),
                DenseVectorRecord(
                    chunk_id=archived_chunk.id,
                    document_id=document.id,
                    version_id=archived_version.id,
                    department_id="dept_tax",
                    embedding=[1.0, 0.0, 0.0, 0.0],
                ),
            ]
        )
        retriever = HybridEvidenceRetriever(
            bm25=sparse,
            dense=dense,
            embedder=FixedIntegrationEmbedder(),
            canonical_store=repository,
            reranker=CrossEncoderReranker(model_name=settings.reranker_model),
        )
        nodes = FixedDagNodes(
            intent=IntentNode(llm),
            rewrite=RewriteNode(llm),
            route=RouteNode(llm, rules=_DEPARTMENT_RULES),
            retrieve=RetrieveNode(retriever),
            answer=AnswerNode(llm),
            verify=VerifyNode(llm),
        )
        user = User(
            id=f"user_harness_{suffix}",
            email=f"harness-{suffix}@example.local",
            password_hash=hash_password("demo-user"),
            role=Role.USER,
            created_at=now,
        )
        app = create_app(
            settings=settings,
            user_store=InMemoryUserStore([user]),
            document_repository=repository,
            trace_store=trace_store,
            chat_service=HarnessChatService(PolicyHarness(nodes, trace_store=trace_store)),
        )
        trace_id = f"trace_chat_{suffix}"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/chat",
                headers={
                    "Authorization": f"Bearer {create_access_token(user, settings)}",
                    "X-Trace-Id": trace_id,
                },
                json={"query": "小规模纳税人有哪些增值税优惠？", "session_id": "it01"},
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "SUCCESS"
        assert payload["verification"]["passed"] is True
        assert [item["chunk_id"] for item in payload["citations"]] == [active_chunk.id]
        persisted = await trace_store.get(trace_id)
        assert persisted is not None
        assert persisted.status.value == "SUCCESS"
        assert persisted.retrieval_metadata["canonical_candidate_count"] == 1
        assert [node.node for node in persisted.nodes] == [
            "Intent",
            "Rewrite",
            "Route",
            "Retrieve",
            "Answer",
            "Verify",
        ]
    finally:
        await dense.drop_collection()
        await sparse.delete_index()
        await sparse.close()
        await _cleanup(repository, document_id)
        await repository.close()
        await trace_store.close()


@pytest.mark.integration
async def test_it06_real_empty_retrieval_abstains_without_citations() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1.")

    suffix = uuid4().hex
    settings = Settings(
        mongo_uri="mongodb://localhost:27017",
        mongo_db=f"zhengheng_harness_gap_it_{suffix}",
        opensearch_url="http://localhost:9201",
        milvus_host="localhost",
        reranker_enabled=True,
    )
    repository = MongoDocumentRepository(settings)
    sparse = OpenSearchBM25(settings, index_name=f"policy_chunks_harness_gap_it_{suffix}")
    dense = MilvusDenseIndex(
        settings,
        embedding_dim=4,
        embedding_model="integration-fixture-vector-v1",
        collection_name=f"policy_chunks_harness_gap_it_{suffix}",
    )
    trace_store = MongoTraceStore(settings)
    llm = FakeLLM(
        structured_fixtures={
            "intent": {"intent": "POLICY_QUERY", "confidence": 1.0},
            "rewrite": {"queries": ["不存在的政策问题"]},
            "route": {"routes": [{"department_id": "dept_tax", "score": 1.0}]},
        }
    )
    try:
        await repository.initialize_indexes()
        await sparse.initialize()
        await dense.initialize()
        retriever = HybridEvidenceRetriever(
            bm25=sparse,
            dense=dense,
            embedder=FixedIntegrationEmbedder(),
            canonical_store=repository,
            reranker=CrossEncoderReranker(model_name=settings.reranker_model),
        )
        nodes = FixedDagNodes(
            intent=IntentNode(llm),
            rewrite=RewriteNode(llm),
            route=RouteNode(llm, rules=_DEPARTMENT_RULES),
            retrieve=RetrieveNode(retriever),
            answer=AnswerNode(llm),
            verify=VerifyNode(llm),
        )
        result = await HarnessChatService(PolicyHarness(nodes, trace_store=trace_store)).answer(
            query="不存在的政策问题",
            trace_id=f"trace_gap_{suffix}",
            session_id="it06",
            user_id="user_gap",
        )

        assert result.status.value == "ABSTAIN"
        assert result.citations == []
        assert result.answer == "当前有效政策证据不足，暂不作答。"
        trace = await trace_store.get(f"trace_gap_{suffix}")
        assert trace is not None
        assert trace.status.value == "ABSTAIN"
        assert trace.citations == []
    finally:
        await dense.drop_collection()
        await sparse.delete_index()
        await sparse.close()
        await repository.close()
        await trace_store.close()
