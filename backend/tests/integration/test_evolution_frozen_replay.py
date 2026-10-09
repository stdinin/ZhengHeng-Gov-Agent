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
from backend.app.evolution.deploy import stable_bucket
from backend.app.evolution.frozen_replay import FrozenTraceReplayExecutor
from backend.app.evolution.models import (
    ActionType,
    ExperimentBucket,
    ExperimentStatus,
    Feedback,
    FeedbackType,
    StrategyCandidate,
    StrategyStatus,
)
from backend.app.evolution.repository import MongoEvolutionRepository
from backend.app.evolution.service import EvolutionService, FeedbackService
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
from backend.app.harness.state import DepartmentRoute, IntentDecision, RouteDecision
from backend.app.llm.fake import FakeLLM
from backend.app.retrieval.bm25 import BM25ChunkRecord, OpenSearchBM25
from backend.app.retrieval.dense import DenseVectorRecord, MilvusDenseIndex
from backend.app.retrieval.hybrid import HybridEvidenceRetriever
from backend.app.storage.document_repository import MongoDocumentRepository
from backend.app.storage.trace_repository import MongoTraceStore


class _FixedEmbedder:
    async def embed(self, query: str) -> list[float]:
        del query
        return [1.0, 0.0, 0.0, 0.0]


class _FixedRoute:
    async def run(self, queries: list[str], intent: IntentDecision) -> RouteDecision:
        del queries, intent
        return RouteDecision(
            routes=[DepartmentRoute(department_id="other", score=1.0, reason="fixture")]
        )


class _RouteAdapter(RouteNode):
    def __init__(self, route: _FixedRoute) -> None:
        self._route = route

    async def run(self, queries: list[str], intent: IntentDecision) -> RouteDecision:
        return await self._route.run(queries, intent)


async def _cleanup(repository: MongoDocumentRepository, document_id: str) -> None:
    await repository._chunks.delete_many({"document_id": document_id})
    await repository._versions.delete_many({"document_id": document_id})
    await repository._documents.delete_one({"_id": document_id})


@pytest.mark.integration
async def test_it04_real_frozen_trace_replay_recomputes_metrics_and_persists_gray_path() -> None:
    """A candidate may enter gray only after a real saved trace is replayed."""

    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1.")

    suffix = uuid4().hex
    settings = Settings(
        mongo_uri="mongodb://localhost:27017",
        mongo_db=f"zhengheng_replay_it_{suffix}",
        opensearch_url="http://localhost:9201",
        milvus_host="localhost",
        reranker_enabled=False,
    )
    now = datetime.now(UTC)
    document_id = f"doc_replay_{suffix}"
    version_id = f"ver_replay_{suffix}"
    chunk_id = f"chunk_replay_{suffix}"
    trace_id = f"trace_replay_source_{suffix}"
    repository = MongoDocumentRepository(settings)
    evolution = MongoEvolutionRepository(settings)
    trace_store = MongoTraceStore(settings)
    sparse = OpenSearchBM25(settings, index_name=f"policy_chunks_replay_it_{suffix}")
    dense = MilvusDenseIndex(
        settings,
        embedding_dim=4,
        embedding_model="integration-fixture-vector-v1",
        collection_name=f"policy_chunks_replay_it_{suffix}",
    )
    strategy_id = f"strategy_replay_{suffix}"
    rollout_document_id = f"doc_rollout_{suffix}"
    try:
        document = Document(
            id=document_id,
            logical_name="小规模纳税人增值税优惠",
            department_id="dept_tax",
            source_type=SourceType.DATASET,
            current_active_version_id=version_id,
            created_at=now,
            updated_at=now,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_no=1,
            sha256=sha256(suffix.encode()).hexdigest(),
            status=DocumentVersionStatus.ACTIVE,
            policy_status=PolicyStatus.FULLY_EFFECTIVE,
            title=document.logical_name,
            raw_text="符合条件的小规模纳税人可以适用增值税优惠。",
            trace_id=f"seed_{suffix}",
            created_at=now,
            updated_at=now,
        )
        chunk = Chunk(
            id=chunk_id,
            document_id=document_id,
            version_id=version_id,
            ordinal=1,
            text=version.raw_text,
            trace_id=version.trace_id,
            created_at=now,
            updated_at=now,
        )
        await repository.initialize_indexes()
        await evolution.initialize_indexes()
        await repository.create_document(document)
        await repository.create_version(version)
        await repository.create_chunks([chunk])
        await sparse.initialize()
        await dense.initialize()
        await sparse.index_records(
            [
                BM25ChunkRecord(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    version_id=version.id,
                    department_id=document.department_id,
                    title=version.title,
                    text=chunk.text,
                )
            ]
        )
        await dense.upsert(
            [
                DenseVectorRecord(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    version_id=version.id,
                    department_id=document.department_id,
                    embedding=[1.0, 0.0, 0.0, 0.0],
                )
            ]
        )
        llm = FakeLLM(
            structured_fixtures={
                "intent": {"intent": "POLICY_QUERY", "confidence": 1.0},
                "rewrite": {"queries": ["小规模纳税人增值税优惠"]},
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
                    "reason": "原文直接支持。",
                },
            }
        )
        retriever = HybridEvidenceRetriever(
            bm25=sparse,
            dense=dense,
            embedder=_FixedEmbedder(),
            canonical_store=repository,
            reranker=None,
            reranker_enabled=False,
        )
        nodes = FixedDagNodes(
            intent=IntentNode(llm),
            rewrite=RewriteNode(llm),
            route=_RouteAdapter(_FixedRoute()),
            retrieve=RetrieveNode(retriever),
            answer=AnswerNode(llm),
            verify=VerifyNode(llm),
        )
        harness = PolicyHarness(nodes, trace_store=trace_store)
        source = await harness.run(
            query="小规模纳税人有何优惠？",
            trace_id=trace_id,
            session_id=f"session_{suffix}",
            user_id=f"user_{suffix}",
            now=now,
        )
        assert source.status.value == "ABSTAIN"
        persisted_source = await trace_store.get(trace_id)
        assert persisted_source is not None
        assert persisted_source.retrieval_hits == []

        feedback = Feedback(
            id=f"feedback_{suffix}",
            trace_id=trace_id,
            user_id=f"user_{suffix}",
            feedback_type=FeedbackType.DISLIKE,
            text="没有检索到应有的税务政策。",
            created_at=now,
        )
        badcase = await FeedbackService(evolution).record(feedback)
        assert badcase is not None
        service = EvolutionService(
            evolution,
            replay_executor=FrozenTraceReplayExecutor(harness=harness, trace_store=trace_store),
        )
        proposed = await service.propose_strategy(
            badcase.id,
            StrategyCandidate(
                id=strategy_id,
                version=1,
                status=StrategyStatus.CANDIDATE,
                name="税务部门提示",
                created_by="admin_it",
                actions=[
                    {
                        "action_type": ActionType.DEPARTMENT_HINT,
                        "department_id": "dept_tax",
                    }
                ],
            ),
        )

        replayed = await service.replay_from_frozen_traces(
            strategy_id=proposed.id,
            source_trace_ids=[trace_id],
        )
        report = await evolution.get_replay_report(replayed.replay_report_id or "")

        assert replayed.status is StrategyStatus.REPLAY_PASSED
        assert report is not None
        assert report.baseline.success_rate == 0.0
        assert report.candidate.success_rate == 1.0
        assert report.source_trace_ids == [trace_id]
        assert report.candidate_trace_ids and report.candidate_trace_ids[0] != trace_id
        candidate_trace = await trace_store.get(report.candidate_trace_ids[0])
        assert candidate_trace is not None
        assert candidate_trace.status.value == "SUCCESS"
        assert candidate_trace.retrieval_hits == [chunk_id]
        assert candidate_trace.matched_strategies == [f"{strategy_id}:v1"]
        assert candidate_trace.department_routes[0]["department_id"] == "dept_tax"

        grayed = await service.approve_gray(replayed.id, rollout_percent=10, approved_by="admin_it")
        assert grayed.status is StrategyStatus.GRAY

        # Simulate a real corpus change after replay: the tax policy becomes archived,
        # while a canonical "other" policy is published. The gray strategy still pins
        # traffic to dept_tax, so its real treatment traces must now degrade and roll back.
        await repository.archive_version(version_id)
        rollout_version = DocumentVersion(
            id=f"ver_rollout_{suffix}",
            document_id=rollout_document_id,
            version_no=1,
            sha256=sha256(f"rollout:{suffix}".encode()).hexdigest(),
            status=DocumentVersionStatus.ACTIVE,
            policy_status=PolicyStatus.FULLY_EFFECTIVE,
            title="综合便民服务政策",
            raw_text="综合便民服务事项可在线办理。",
            trace_id=f"seed_rollout_{suffix}",
            created_at=now,
            updated_at=now,
        )
        rollout_document = Document(
            id=rollout_document_id,
            logical_name=rollout_version.title,
            department_id="other",
            source_type=SourceType.DATASET,
            current_active_version_id=rollout_version.id,
            created_at=now,
            updated_at=now,
        )
        rollout_chunk = Chunk(
            id=f"chunk_rollout_{suffix}",
            document_id=rollout_document.id,
            version_id=rollout_version.id,
            ordinal=1,
            text=rollout_version.raw_text,
            trace_id=rollout_version.trace_id,
            created_at=now,
            updated_at=now,
        )
        await repository.create_document(rollout_document)
        await repository.create_version(rollout_version)
        await repository.create_chunks([rollout_chunk])
        await sparse.index_records(
            [
                BM25ChunkRecord(
                    chunk_id=rollout_chunk.id,
                    document_id=rollout_document.id,
                    version_id=rollout_version.id,
                    department_id=rollout_document.department_id,
                    title=rollout_version.title,
                    text=rollout_chunk.text,
                )
            ]
        )
        await dense.upsert(
            [
                DenseVectorRecord(
                    chunk_id=rollout_chunk.id,
                    document_id=rollout_document.id,
                    version_id=rollout_version.id,
                    department_id=rollout_document.department_id,
                    embedding=[1.0, 0.0, 0.0, 0.0],
                )
            ]
        )

        assert stable_bucket("stable-user", "stable-session", grayed.id, grayed.version) == (
            stable_bucket("stable-user", "stable-session", grayed.id, grayed.version)
        )
        for ordinal in range(50):
            control_trace_id = f"gray_control_{suffix}_{ordinal}"
            treatment_trace_id = f"gray_treatment_{suffix}_{ordinal}"
            control = await harness.run(
                query="便民服务如何办理？",
                trace_id=control_trace_id,
                session_id=f"control_session_{ordinal}",
                user_id=f"control_user_{ordinal}",
                now=datetime.now(UTC),
            )
            treatment = await harness.run(
                query="便民服务如何办理？",
                trace_id=treatment_trace_id,
                session_id=f"treatment_session_{ordinal}",
                user_id=f"treatment_user_{ordinal}",
                now=datetime.now(UTC),
                strategy=grayed,
            )
            assert control.status.value == "SUCCESS"
            assert treatment.status.value == "ABSTAIN"
            await service.record_execution_from_trace(
                grayed.id,
                trace_id=control_trace_id,
                bucket=ExperimentBucket.CONTROL,
            )
            await service.record_execution_from_trace(
                grayed.id,
                trace_id=treatment_trace_id,
                bucket=ExperimentBucket.TREATMENT,
            )

        rollback = await service.monitor_gray_and_maybe_rollback(grayed.id)
        rolled_back = await evolution.get_strategy(grayed.id)
        experiments = await evolution.list_experiments(strategy_id=grayed.id)

        assert rollback.rollback is True
        assert rolled_back is not None
        assert rolled_back.status is StrategyStatus.ROLLED_BACK
        assert experiments[0].status is ExperimentStatus.ROLLED_BACK
        assert experiments[0].control_n == 50
        assert experiments[0].treatment_n == 50
    finally:
        await dense.drop_collection()
        await sparse.delete_index()
        await sparse.close()
        await _cleanup(repository, document_id)
        await _cleanup(repository, rollout_document_id)
        await repository.close()
        await trace_store.close()
        await evolution.close()
