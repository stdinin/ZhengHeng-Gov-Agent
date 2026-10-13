"""API-facing adapter for the multi-agent global orchestrator."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import UTC, datetime
from inspect import isawaitable

from backend.app.agents.memory import MultiAgentMemoryCoordinator
from backend.app.agents.orchestrator import GlobalOrchestrator
from backend.app.harness.chat_service import ChatServiceUnavailable
from backend.app.harness.policy import PolicyHarnessResult

logger = logging.getLogger(__name__)


class MultiAgentChatService:
    def __init__(
        self,
        orchestrator: GlobalOrchestrator,
        *,
        resources: tuple[object, ...],
        memory: MultiAgentMemoryCoordinator | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._resources = resources
        self._memory = memory

    async def answer(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str,
    ) -> PolicyHarnessResult:
        try:
            memory_snapshot = (
                await self._memory.build_snapshot(
                    user_id=user_id, session_id=session_id, query=query
                )
                if self._memory is not None
                else {}
            )
            result = await self._orchestrator.run(
                query=query,
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                now=datetime.now(UTC),
                memory_snapshot=memory_snapshot,
            )
            if self._memory is not None:
                await self._memory.write_final_episodic(
                    user_id=user_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    result=result,
                )
            return result
        except Exception as error:
            # Keep the client-facing failure generic, but retain a stack trace
            # without logging the query, user, session, or trace identifier.
            # This is essential for diagnosing a real service dependency while
            # preserving the project's PII-redaction boundary.
            logger.exception("Multi-agent orchestration failed (%s)", type(error).__name__)
            raise ChatServiceUnavailable(
                "The multi-agent retrieval orchestration is unavailable in this deployment."
            ) from error

    async def close(self) -> None:
        seen: set[int] = set()
        for resource in self._resources:
            if id(resource) in seen:
                continue
            seen.add(id(resource))
            close = getattr(resource, "close", None)
            if callable(close):
                outcome: object | Awaitable[object] = close()
                if isawaitable(outcome):
                    await outcome
