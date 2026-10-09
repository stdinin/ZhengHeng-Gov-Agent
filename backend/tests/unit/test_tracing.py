from datetime import UTC, datetime

from backend.app.harness.state import (
    AgentState,
    AnswerStatus,
    IntentDecision,
    IntentKind,
    VerificationResult,
)
from backend.app.observability.tracing import TraceRecorder


def test_trace_recorder_keeps_node_order_latency_and_strategy_provenance() -> None:
    recorder = TraceRecorder(
        trace_id="trace_001",
        user_id="user_001",
        session_id="session_001",
        query="增值税优惠",
        created_at=datetime.now(UTC),
    )
    recorder.record_node(
        node="Route",
        input_summary="增值税优惠",
        output_summary="dept_tax",
        latency_ms=12.5,
        applied_strategy_ids=["strategy_route_1"],
    )
    trace = recorder.finish(status=AnswerStatus.SUCCESS, answer="答案 [C1]")

    assert trace.id == "trace_001"
    assert trace.nodes[0].node == "Route"
    assert trace.nodes[0].latency_ms == 12.5
    assert trace.nodes[0].applied_strategy_ids == ["strategy_route_1"]
    assert trace.status is AnswerStatus.SUCCESS


def test_trace_recorder_persists_the_required_safe_agent_state_fields() -> None:
    recorder = TraceRecorder(
        trace_id="trace_full_001",
        user_id="user_001",
        session_id="session_001",
        query="身份证11010519491231002X 的增值税优惠",
        created_at=datetime.now(UTC),
    )
    state = AgentState(
        trace_id="trace_full_001",
        user_id="user_001",
        session_id="session_001",
        raw_query="身份证11010519491231002X 的增值税优惠",
        normalized_query="手机号 13800138000 的增值税优惠",
        intent=IntentDecision(intent=IntentKind.POLICY_QUERY, confidence=0.95),
        rewritten_queries=["邮箱 user@example.com 的增值税优惠"],
        memory_context=["身份证 11010519491231002X"],
        retrieval_hits=["chunk_1"],
        citations=["C1"],
        verification=VerificationResult(
            passed=True,
            warnings=["请联系 user@example.com"],
        ),
        retry_count=0,
        status=AnswerStatus.SUCCESS,
        timings_ms={"Intent": 1.2, "total": 4.5},
    )

    trace = recorder.finish(
        status=AnswerStatus.SUCCESS,
        answer="符合条件的主体可享受优惠。 [C1]",
        state=state,
        citation_cards=[
            {
                "id": "C1",
                "chunk_id": "chunk_1",
                "excerpt": "联系电话 13800138000",
            }
        ],
    )

    assert trace.normalized_query == "手机号 [REDACTED_PHONE] 的增值税优惠"
    assert trace.intent == {
        "intent": "POLICY_QUERY",
        "entities": {
            "location": None,
            "dates": [],
            "document_numbers": [],
            "departments": [],
            "policy_terms": [],
        },
        "confidence": 0.95,
        "used_fallback": False,
    }
    assert trace.retrieval_hits == ["chunk_1"]
    assert trace.citations[0]["id"] == "C1"
    serialized = repr(trace)
    assert "11010519491231002X" not in serialized
    assert "13800138000" not in serialized
    assert "user@example.com" not in serialized
    assert trace.timings_ms["total"] == 4.5
