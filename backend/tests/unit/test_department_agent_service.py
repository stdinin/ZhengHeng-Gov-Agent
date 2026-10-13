from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.citations import Evidence
from backend.app.observability.tracing import TraceRecord


def test_department_request_rejects_any_attempt_to_override_service_department() -> None:
    from backend.app.agents.models import DepartmentExecutionRequest

    with pytest.raises(ValidationError):
        DepartmentExecutionRequest.model_validate(
            {
                "parent_trace_id": "parent-trace-1",
                "request_id": "request-1",
                "query": "个税优惠",
                "rewritten_query": "个税优惠",
                "user_id": "user-1",
                "deadline_ms": 1_000,
                "dept_id": "housing",
            }
        )


def test_default_agent_registry_is_static_and_has_three_enabled_departments() -> None:
    from backend.app.agents.registry import default_department_agent_registry

    registry = default_department_agent_registry()

    assert [definition.dept_id for definition in registry.enabled_definitions()] == [
        "tax",
        "hrss",
        "housing",
    ]
    assert registry.get_by_department("tax").agent_id == "tax-agent"
    assert registry.get_by_department("not-registered") is None


def test_registry_accepts_operator_supplied_static_json_definition() -> None:
    from backend.app.agents.registry import department_agent_registry_from_settings
    from backend.app.config import Settings

    registry = department_agent_registry_from_settings(
        Settings(
            department_agents_json=(
                '[{"agent_id":"tax-v2","dept_id":"tax","display_name":"Tax",'
                '"base_url":"http://tax-v2:8000","enabled":true,"timeout_ms":9000,'
                '"max_concurrency":3}]'
            )
        )
    )

    definition = registry.get_by_department("tax")
    assert definition is not None
    assert definition.agent_id == "tax-v2"
    assert definition.timeout_ms == 9_000


def test_default_registry_inherits_the_bounded_deployment_timeout() -> None:
    from backend.app.agents.registry import department_agent_registry_from_settings
    from backend.app.config import Settings

    registry = department_agent_registry_from_settings(Settings(department_agent_timeout_ms=20_000))

    assert [item.timeout_ms for item in registry.enabled_definitions()] == [20_000, 20_000, 20_000]


@pytest.mark.asyncio
async def test_department_executor_forces_its_immutable_scope_and_persists_child_trace() -> None:
    from backend.app.agents.department_service import DepartmentAgentExecutor
    from backend.app.agents.models import DepartmentExecutionRequest, DepartmentExecutionStatus
    from backend.app.runtime.base import RuntimeNode
    from backend.app.runtime.fake import FakeRuntime
    from backend.app.runtime.registry import RuntimeLLMClient

    @dataclass
    class RecordingRetriever:
        requested_departments: list[list[str]] = field(default_factory=list)

        async def retrieve(
            self, *, queries: list[str], department_ids: list[str], limit: int
        ) -> list[Evidence]:
            del queries, limit
            self.requested_departments.append(department_ids)
            return [
                Evidence(
                    chunk_id="tax-chunk-1",
                    document_id="tax-doc-1",
                    version_id="tax-version-1",
                    title="税收政策",
                    department="tax",
                    status=DocumentVersionStatus.ACTIVE,
                    text="符合条件的主体可以享受税收优惠。",
                )
            ]

    @dataclass
    class RecordingTraceStore:
        traces: list[TraceRecord] = field(default_factory=list)

        async def save(self, trace: TraceRecord) -> None:
            self.traces.append(trace)

        async def get(self, trace_id: str) -> TraceRecord | None:
            return next((trace for trace in self.traces if trace.id == trace_id), None)

        async def list_for_user(
            self, user_id: str, *, session_id: str | None = None, limit: int = 50
        ) -> list[TraceRecord]:
            traces = [trace for trace in self.traces if trace.user_id == user_id]
            if session_id is not None:
                traces = [trace for trace in traces if trace.session_id == session_id]
            return traces[:limit]

    retriever = RecordingRetriever()
    trace_store = RecordingTraceStore()
    runtime = RuntimeLLMClient(
        FakeRuntime(
            fixtures={
                RuntimeNode.ANSWER: {
                    "answer": "符合条件的主体可以享受税收优惠。",
                    "claims": [
                        {"text": "符合条件的主体可以享受税收优惠。", "citation_ids": ["C1"]}
                    ],
                },
                RuntimeNode.VERIFY: {
                    "supported": True,
                    "support_score": 1,
                    "contradiction": False,
                    "reason": "supported",
                },
            }
        )
    )
    executor = DepartmentAgentExecutor(
        agent_id="tax-agent",
        dept_id="tax",
        retriever=retriever,
        llm=runtime,
        trace_store=trace_store,
    )

    result = await executor.execute(
        DepartmentExecutionRequest(
            parent_trace_id="parent-trace-1",
            request_id="request-1",
            query="个税优惠",
            rewritten_query="个税优惠",
            user_id="user-1",
            deadline_ms=1_000,
        ),
        now=datetime.now(UTC),
    )

    assert result.status is DepartmentExecutionStatus.SUCCESS
    assert result.agent_id == "tax-agent"
    assert result.dept_id == "tax"
    assert result.local_verifier_pass is True
    assert retriever.requested_departments == [["tax"]]
    child_trace = trace_store.traces[0]
    assert child_trace.parent_trace_id == "parent-trace-1"
    assert child_trace.trace_kind == "child"
    assert child_trace.agent_id == "tax-agent"
    assert child_trace.dept_id == "tax"
    assert child_trace.citations[0]["document_id"] == "tax-doc-1"
    assert child_trace.verification == {"passed": True, "error_code": None}


@pytest.mark.asyncio
async def test_department_executor_preserves_real_retrieval_stage_metadata_in_child_trace() -> None:
    from backend.app.agents.department_service import DepartmentAgentExecutor
    from backend.app.agents.models import DepartmentExecutionRequest
    from backend.app.runtime.base import RuntimeNode
    from backend.app.runtime.fake import FakeRuntime
    from backend.app.runtime.registry import RuntimeLLMClient

    @dataclass(frozen=True)
    class RetrievalTrace:
        bm25_candidate_count: int = 5
        dense_candidate_count: int = 4
        fused_candidate_count: int = 3
        rerank_input_count: int = 3
        reranked_candidate_count: int = 2
        canonical_candidate_count: int = 1
        reranker_skipped: bool = False

    @dataclass(frozen=True)
    class RetrievalResult:
        evidence: list[Evidence]
        trace: RetrievalTrace

    @dataclass
    class TraceableRetriever:
        async def retrieve(self, **kwargs: object) -> list[Evidence]:
            del kwargs
            raise AssertionError("traceable retriever path must be used")

        async def retrieve_with_trace(self, **kwargs: object) -> RetrievalResult:
            del kwargs
            return RetrievalResult(
                evidence=[
                    Evidence(
                        chunk_id="tax-chunk-2",
                        document_id="tax-doc-2",
                        version_id="tax-version-2",
                        title="税收政策",
                        department="tax",
                        status=DocumentVersionStatus.ACTIVE,
                        text="真实检索阶段元数据应随 child trace 保存。",
                    )
                ],
                trace=RetrievalTrace(),
            )

    @dataclass
    class TraceStore:
        traces: list[TraceRecord] = field(default_factory=list)

        async def save(self, trace: TraceRecord) -> None:
            self.traces.append(trace)

        async def get(self, trace_id: str) -> TraceRecord | None:
            return None

        async def list_for_user(
            self, user_id: str, *, session_id: str | None = None, limit: int = 50
        ) -> list[TraceRecord]:
            del user_id, session_id, limit
            return []

    store = TraceStore()
    executor = DepartmentAgentExecutor(
        agent_id="tax-agent",
        dept_id="tax",
        retriever=TraceableRetriever(),
        llm=RuntimeLLMClient(
            FakeRuntime(
                fixtures={
                    RuntimeNode.ANSWER: {
                        "answer": "真实检索阶段元数据应随 child trace 保存。",
                        "claims": [
                            {
                                "text": "真实检索阶段元数据应随 child trace 保存。",
                                "citation_ids": ["C1"],
                            }
                        ],
                    },
                    RuntimeNode.VERIFY: {
                        "supported": True,
                        "support_score": 1,
                        "contradiction": False,
                        "reason": "supported",
                    },
                }
            )
        ),
        trace_store=store,
    )

    result = await executor.execute(
        DepartmentExecutionRequest(
            parent_trace_id="parent-trace-2",
            request_id="request-2",
            query="税收政策",
            rewritten_query="税收政策",
        ),
        now=datetime.now(UTC),
    )

    assert result.local_verifier_pass is True
    assert store.traces[0].retrieval_metadata == {
        "bm25_candidate_count": 5,
        "dense_candidate_count": 4,
        "fused_candidate_count": 3,
        "rerank_input_count": 3,
        "reranked_candidate_count": 2,
        "canonical_candidate_count": 1,
        "reranker_skipped": False,
    }
