from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from backend.app.config import Settings
from backend.app.evolution.models import Feedback
from backend.app.main import create_app
from backend.app.security.auth import User, create_access_token, hash_password
from backend.app.security.rbac import Role
from backend.app.storage.users import InMemoryUserStore


@dataclass
class RecordingFeedbackService:
    recorded: list[Feedback] = field(default_factory=list)

    async def record(self, feedback: Feedback) -> None:
        self.recorded.append(feedback)
        return None


async def test_feedback_api_records_user_feedback() -> None:
    settings = Settings(app_secret="test-secret-that-is-at-least-32-bytes")
    user = User(
        id="user_demo",
        email="user@example.local",
        password_hash=hash_password("demo-user"),
        role=Role.USER,
        created_at=datetime.now(UTC),
    )
    service = RecordingFeedbackService()
    app = create_app(
        settings=settings,
        user_store=InMemoryUserStore([user]),
        feedback_service=service,
    )
    headers = {"Authorization": f"Bearer {create_access_token(user, settings)}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/feedback",
            headers=headers,
            json={"trace_id": "trace_1", "type": "DISLIKE", "text": "引用不准确"},
        )

    assert response.status_code == 201
    assert response.json()["type"] == "DISLIKE"
    assert service.recorded[0].feedback_type.value == "DISLIKE"
