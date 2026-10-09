from datetime import UTC, datetime
from typing import Protocol

from backend.app.harness.policy import PolicyHarness, PolicyHarnessResult


class ChatService(Protocol):
    async def answer(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str,
    ) -> PolicyHarnessResult: ...


class ChatServiceUnavailable(RuntimeError):
    """The API is present, but no real retrieval-backed harness is available."""


class HarnessChatService:
    """Thin API-facing adapter around the fixed, trace-persisting policy harness."""

    def __init__(self, harness: PolicyHarness) -> None:
        self._harness = harness

    @property
    def harness(self) -> PolicyHarness:
        return self._harness

    async def answer(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str,
    ) -> PolicyHarnessResult:
        try:
            return await self._harness.run(
                query=query,
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                now=datetime.now(UTC),
            )
        except ChatServiceUnavailable:
            raise
        except Exception as error:
            raise ChatServiceUnavailable(
                "The real retrieval-backed chat harness is unavailable in this deployment."
            ) from error


class UnavailableChatService:
    """Never fabricates an answer when the real retrieval composition is unavailable."""

    async def answer(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str,
    ) -> PolicyHarnessResult:
        del query, trace_id, session_id, user_id
        raise ChatServiceUnavailable(
            "The real retrieval-backed chat harness is unavailable in this deployment."
        )
