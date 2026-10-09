from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.app.api.errors import ApiError
from backend.app.evolution.models import BadCase, Feedback, FeedbackType
from backend.app.security.auth import decode_access_token
from backend.app.storage.users import UserStore

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


class FeedbackRecorder(Protocol):
    async def record(self, feedback: Feedback) -> BadCase | None: ...


class CreateFeedbackRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)
    feedback_type: FeedbackType = Field(alias="type")
    text: str | None = Field(default=None, max_length=4_000)


def _service(request: Request) -> FeedbackRecorder:
    return cast(FeedbackRecorder, request.app.state.feedback_service)


def _user_store(request: Request) -> UserStore:
    return cast(UserStore, request.app.state.user_store)


async def _authenticate(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(status_code=401, code="AUTH_REQUIRED", message="Bearer token is required.")
    try:
        user_id = decode_access_token(token, request.app.state.settings)
    except ValueError as error:
        raise ApiError(status_code=401, code="INVALID_TOKEN", message=str(error)) from error
    if await _user_store(request).get_by_id(user_id) is None:
        raise ApiError(
            status_code=401,
            code="INVALID_TOKEN",
            message="Token user no longer exists.",
        )
    return user_id


@router.post("", response_model=Feedback, status_code=201)
async def create_feedback(payload: CreateFeedbackRequest, request: Request) -> Feedback:
    user_id = await _authenticate(request)
    feedback = Feedback(
        id=str(uuid4()),
        trace_id=payload.trace_id,
        user_id=user_id,
        feedback_type=payload.feedback_type,
        text=payload.text,
        created_at=datetime.now(UTC),
    )
    await _service(request).record(feedback)
    return feedback
