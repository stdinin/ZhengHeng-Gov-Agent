from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.app.evolution.models import (
    BadCase,
    Feedback,
    FeedbackType,
    ObservationReason,
    StrategyCandidate,
)
from backend.app.evolution.service import FeedbackService
from backend.app.harness.state import AnswerStatus
from backend.app.observability.tracing import TraceRecord


@dataclass
class Repository:
    feedback: list[Feedback] = field(default_factory=list)
    badcases: list[BadCase] = field(default_factory=list)

    async def save_feedback(self, feedback: Feedback) -> None:
        self.feedback.append(feedback)

    async def save_badcase(self, badcase: BadCase) -> None:
        self.badcases.append(badcase)


@dataclass
class TraceStore:
    traces: dict[str, TraceRecord]

    async def get(self, trace_id: str) -> TraceRecord | None:
        return self.traces.get(trace_id)


async def test_multi_agent_timeout_feedback_creates_attributed_badcase_without_strategy() -> None:
    now = datetime.now(UTC)
    root_trace = TraceRecord(
        id="root-timeout",
        user_id="user-1",
        session_id="session-1",
        query="跨部门咨询",
        nodes=[],
        status=AnswerStatus.SUCCESS,
        answer="partial",
        created_at=now,
        updated_at=now,
        execution_mode="multi_agent",
        selected_departments=["tax", "hrss"],
        child_trace_ids=["child-tax"],
        partial=True,
        failed_departments=[{"dept_id": "hrss", "reason": "timeout"}],
        final_verification={"passed": True, "warnings": []},
    )
    repository = Repository()
    service = FeedbackService(
        repository, trace_store=TraceStore({"root-timeout": root_trace})
    )

    badcase = await service.record(
        Feedback(
            id="feedback-1",
            trace_id="root-timeout",
            user_id="user-1",
            feedback_type=FeedbackType.DISLIKE,
            created_at=now,
        )
    )

    assert badcase is not None
    assert badcase.reason is ObservationReason.AGENT_TIMEOUT
    assert badcase.orchestration_stage == "department_dispatch"
    assert badcase.agent_id is None
    assert badcase.dept_id is None
    assert repository.feedback[0].id == "feedback-1"
    assert repository.badcases[0].id == badcase.id


def test_strategy_scope_adds_multi_agent_targeting_without_changing_dsl_actions() -> None:
    strategy = StrategyCandidate.model_validate(
        {
            "id": "dept-tax-strategy",
            "version": 1,
            "status": "CANDIDATE",
            "scope": {"mode": "department", "dept_id": "tax"},
            "actions": [{"type": "QUERY_EXPAND", "terms": ["税务登记"]}],
        }
    )

    assert strategy.scope.mode == "department"
    assert strategy.scope.dept_id == "tax"
    with pytest.raises(ValueError, match="requires dept_id"):
        StrategyCandidate.model_validate(
            {
                "id": "invalid-dept-strategy",
                "version": 1,
                "status": "CANDIDATE",
                "scope": {"mode": "department"},
                "actions": [{"type": "QUERY_EXPAND", "terms": ["税务登记"]}],
            }
        )
