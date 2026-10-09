from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.app.evolution.models import Feedback, FeedbackType
from backend.app.evolution.service import FeedbackService


@dataclass
class RecordingEvolutionRepository:
    feedback: list[Feedback] = field(default_factory=list)
    badcases: list[dict[str, object]] = field(default_factory=list)

    async def save_feedback(self, feedback: Feedback) -> None:
        self.feedback.append(feedback)

    async def save_badcase(self, badcase: dict[str, object]) -> None:
        self.badcases.append(badcase)


async def test_dislike_feedback_creates_an_observable_badcase() -> None:
    repository = RecordingEvolutionRepository()
    feedback = Feedback(
        id="feedback_1",
        trace_id="trace_1",
        user_id="user_1",
        feedback_type=FeedbackType.DISLIKE,
        text="引用不准确",
        created_at=datetime.now(UTC),
    )

    badcase = await FeedbackService(repository).record(feedback)

    assert repository.feedback == [feedback]
    assert badcase is not None
    assert badcase.reason.value == "CITATION_ERROR"
