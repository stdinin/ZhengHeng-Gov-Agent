from backend.app.agents.models import (
    DepartmentAgentResult,
    DepartmentCitation,
    DepartmentExecutionStatus,
)
from backend.app.runtime.context import runtime_request_scope


def citation(
    citation_id: str,
    *,
    chunk_id: str,
    dept_id: str,
    status: str = "ACTIVE",
) -> DepartmentCitation:
    return DepartmentCitation(
        id=citation_id,
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        version_id=f"version-{chunk_id}",
        title=f"title-{chunk_id}",
        department=dept_id,
        status=status,
        excerpt=f"evidence-{chunk_id}",
    )


def result(
    dept_id: str,
    *,
    answer: str,
    citations: list[DepartmentCitation],
    verified: bool = True,
) -> DepartmentAgentResult:
    return DepartmentAgentResult(
        agent_id=f"{dept_id}-agent",
        dept_id=dept_id,
        status=DepartmentExecutionStatus.SUCCESS,
        answer=answer,
        citations=citations,
        evidence_count=len(citations),
        local_verifier_pass=verified,
        child_trace_id=f"child-{dept_id}",
        latency_ms=1,
        runtime_backend="pi",
    )


async def test_aggregator_deduplicates_citations_and_drops_unverified_or_stale_sections() -> None:
    from backend.app.agents.aggregator import MultiAgentAggregator

    aggregation = await MultiAgentAggregator().aggregate(
        [
            result(
                "tax",
                answer="税务结论 [C1] [C2]",
                citations=[
                    citation("C1", chunk_id="shared", dept_id="tax"),
                    citation("C2", chunk_id="shared", dept_id="tax"),
                ],
            ),
            result(
                "housing",
                answer="住房结论 [C1]",
                citations=[citation("C1", chunk_id="housing", dept_id="housing")],
            ),
            result(
                "hrss",
                answer="不得出现 [C1]",
                citations=[citation("C1", chunk_id="hrss", dept_id="hrss")],
                verified=False,
            ),
            result(
                "market",
                answer="不得出现 [C1]",
                citations=[
                    citation("C1", chunk_id="market", dept_id="market", status="ARCHIVED")
                ],
            ),
        ]
    )

    assert [section.dept_id for section in aggregation.sections] == ["tax", "housing"]
    assert len(aggregation.citations) == 2
    assert aggregation.answer.count("[C1]") == 2
    assert "税务结论 [C1] [C1]" in aggregation.answer
    assert "不得出现" not in aggregation.answer
    assert aggregation.global_verifier_pass is True


async def test_aggregator_accepts_runtime_order_only_and_records_runtime_audit() -> None:
    from backend.app.agents.aggregator import MultiAgentAggregator
    from backend.app.runtime.base import RuntimeNode
    from backend.app.runtime.fake import FakeRuntime
    from backend.app.runtime.registry import RuntimeLLMClient

    runtime = RuntimeLLMClient(
        FakeRuntime(
            fixtures={
                RuntimeNode.AGGREGATE: {
                    "ordered_department_ids": ["housing", "tax"],
                }
            }
        )
    )
    with runtime_request_scope(trace_id="root", agent_id="orchestrator", dept_id=None):
        aggregation = await MultiAgentAggregator(runtime).aggregate(
            [
                result(
                    "tax",
                    answer="税务结论 [C1]",
                    citations=[citation("C1", chunk_id="tax", dept_id="tax")],
                ),
                result(
                    "housing",
                    answer="住房结论 [C1]",
                    citations=[citation("C1", chunk_id="housing", dept_id="housing")],
                ),
            ]
        )

    assert [section.dept_id for section in aggregation.sections] == ["housing", "tax"]
    assert aggregation.used_fallback is False
    assert aggregation.runtime_events[0]["runtime_backend_used"] == "fake"


async def test_aggregator_rejects_runtime_attempt_to_drop_a_verified_section() -> None:
    from backend.app.agents.aggregator import MultiAgentAggregator
    from backend.app.llm.fake import FakeLLM

    aggregation = await MultiAgentAggregator(
        FakeLLM(structured_fixtures={"aggregate": {"ordered_department_ids": ["tax"]}})
    ).aggregate(
        [
            result(
                "tax",
                answer="税务结论 [C1]",
                citations=[citation("C1", chunk_id="tax", dept_id="tax")],
            ),
            result(
                "housing",
                answer="住房结论 [C1]",
                citations=[citation("C1", chunk_id="housing", dept_id="housing")],
            ),
        ]
    )

    assert [section.dept_id for section in aggregation.sections] == ["tax", "housing"]
    assert aggregation.used_fallback is True
    assert "rejected" in aggregation.warnings[0]
