from collections.abc import Awaitable
from datetime import UTC, datetime
from inspect import isawaitable
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

    def __init__(self, harness: PolicyHarness, *, resources: tuple[object, ...] = ()) -> None:
        self._harness = harness
        self._resources = resources

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

    async def close(self) -> None:
        """Close application-owned remote clients without touching canonical storage."""

        seen: set[int] = set()
        failures: list[Exception] = []
        for resource in self._resources:
            if id(resource) in seen:
                continue
            seen.add(id(resource))
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                outcome: object | Awaitable[object] = close()
                if isawaitable(outcome):
                    await outcome
            except Exception as error:
                failures.append(error)
        if failures:
            raise RuntimeError(
                "One or more chat-service resources failed to close."
            ) from failures[0]


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
