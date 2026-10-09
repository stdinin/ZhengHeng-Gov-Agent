import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from backend.app.config import Settings
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
from backend.app.ingestion.indexer import DocumentIndexer
from backend.app.llm.fake import FakeLLM
from backend.app.main import create_app
from backend.app.retrieval.bm25 import OpenSearchBM25
from backend.app.retrieval.dense import MilvusDenseIndex
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


@pytest.mark.integration
async def test_it02_real_version_switch_keeps_stale_indexes_but_cites_only_v2() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1.")

    suffix = uuid4().hex
    settings = Settings(
        app_secret="test-secret-that-is-at-least-32-bytes",
        mongo_uri="mongodb://localhost:27017",
        mongo_db=f"zhengheng_it02_{suffix}",
        opensearch_url="http://localhost:9201",
        milvus_host="localhost",
    )
    repository = MongoDocumentRepository(settings)
    sparse = OpenSearchBM25(settings, index_name=f"policy_chunks_it02_{suffix}")
    dense = MilvusDenseIndex(
        settings,
        embedding_dim=4,
        embedding_model="integration-fixture-vector-v1",
        collection_name=f"policy_chunks_it02_{suffix}",
    )
    indexer = DocumentIndexer(
        repository=repository,
        sparse=sparse,
        dense=dense,
        embedder=FixedIntegrationEmbedder(),
    )
    trace_store = MongoTraceStore(settings)
    llm = FakeLLM(
        structured_fixtures={
            "intent": {"intent": "POLICY_QUERY", "confidence": 1.0},
            "rewrite": {"queries": ["小规模纳税人增值税优惠"]},
            "route": {"routes": [{"department_id": "dept_tax", "score": 1.0}]},
            "answer": {
                "answer": "v2 规定符合条件的小规模纳税人可享受增值税优惠。",
                "claims": [
                    {
                        "text": "v2 规定符合条件的小规模纳税人可享受增值税优惠。",
                        "citation_ids": ["C1"],
                    }
                ],
            },
            "verify_claim": {
                "supported": True,
                "support_score": 1.0,
                "contradiction": False,
                "reason": "引用的 v2 原文支持该结论。",
            },
        }
    )
    user = User(
        id=f"user_it02_{suffix}",
        email=f"it02-{suffix}@example.local",
        password_hash=hash_password("demo-user"),
        role=Role.USER,
        created_at=datetime.now(UTC),
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
    app = create_app(
        settings=settings,
        user_store=InMemoryUserStore([user]),
        document_repository=repository,
        document_indexer=indexer,
        trace_store=trace_store,
        chat_service=HarnessChatService(PolicyHarness(nodes, trace_store=trace_store)),
    )
    headers = {"Authorization": f"Bearer {create_access_token(user, settings)}"}
    try:
        await repository.initialize_indexes()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            uploaded_v1 = await client.post(
                "/api/v1/documents/upload",
                data={
                    "logical_name": "小规模纳税人优惠政策",
                    "department_id": "dept_tax",
                    "policy_status": "FULLY_EFFECTIVE",
                    "title": "小规模纳税人增值税优惠 v1",
                },
                files={
                    "file": (
                        "v1.md",
                        "# v1\n\n符合条件的小规模纳税人可享受历史增值税优惠。",
                        "text/markdown",
                    )
                },
            )
            assert uploaded_v1.status_code == 201, uploaded_v1.text
            v1 = uploaded_v1.json()
            document_id = v1["document_id"]
            indexed_v1 = await client.post(f"/api/v1/documents/versions/{v1['id']}/reindex")
            assert indexed_v1.status_code == 200
            published_v1 = await client.post(f"/api/v1/documents/versions/{v1['id']}/publish")
            assert published_v1.status_code == 200
            first_chat = await client.post(
                "/api/v1/chat",
                headers={**headers, "X-Trace-Id": f"trace_it02_v1_{suffix}"},
                json={"query": "小规模纳税人有哪些增值税优惠？", "session_id": "it02"},
            )
            assert first_chat.status_code == 200, first_chat.text
            assert first_chat.json()["citations"][0]["version_id"] == v1["id"]

            uploaded_v2 = await client.post(
                "/api/v1/documents/upload",
                data={
                    "logical_name": "小规模纳税人优惠政策",
                    "document_id": document_id,
                    "department_id": "dept_tax",
                    "policy_status": "FULLY_EFFECTIVE",
                    "title": "小规模纳税人增值税优惠 v2",
                },
                files={
                    "file": (
                        "v2.md",
                        "# v2\n\nv2 规定符合条件的小规模纳税人可享受增值税优惠。",
                        "text/markdown",
                    )
                },
            )
            assert uploaded_v2.status_code == 201, uploaded_v2.text
            v2 = uploaded_v2.json()
            indexed_v2 = await client.post(f"/api/v1/documents/versions/{v2['id']}/reindex")
            assert indexed_v2.status_code == 200
            published_v2 = await client.post(f"/api/v1/documents/versions/{v2['id']}/publish")
            assert published_v2.status_code == 200, published_v2.text

            # Do not delete v1 index entries: both backends must still expose
            # stale v1 candidates, leaving Mongo canonical re-check to reject them.
            assert await sparse.count_version_records(v1["id"]) > 0
            assert await dense.count_version_records(v1["id"]) > 0
            final_trace_id = f"trace_it02_v2_{suffix}"
            second_chat = await client.post(
                "/api/v1/chat",
                headers={**headers, "X-Trace-Id": final_trace_id},
                json={"query": "小规模纳税人有哪些增值税优惠？", "session_id": "it02"},
            )

        assert second_chat.status_code == 200, second_chat.text
        assert second_chat.json()["citations"][0]["version_id"] == v2["id"]
        assert (await repository.get_version(v1["id"])).status.value == "ARCHIVED"  # type: ignore[union-attr]
        assert (await repository.get_version(v2["id"])).status.value == "ACTIVE"  # type: ignore[union-attr]
        document = await repository.get_document(document_id)
        assert document is not None and document.current_active_version_id == v2["id"]
        trace = await trace_store.get(final_trace_id)
        assert trace is not None
        assert trace.retrieval_metadata["rerank_input_count"] >= 2
        assert trace.retrieval_metadata["canonical_candidate_count"] == 1
        assert trace.citations[0]["chunk_id"] != first_chat.json()["citations"][0]["chunk_id"]
    finally:
        await dense.drop_collection()
        await sparse.delete_index()
        await sparse.close()
        await repository.close()
        await trace_store.close()
