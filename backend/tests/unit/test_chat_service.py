from datetime import datetime

import pytest

from backend.app.harness.chat_service import ChatServiceUnavailable, HarnessChatService


class FailingHarness:
    async def run(
        self,
        *,
        query: str,
        trace_id: str,
        session_id: str,
        user_id: str,
        now: datetime,
    ) -> object:
        del query, trace_id, session_id, user_id, now
        raise ConnectionError("OpenSearch is unavailable")


async def test_harness_chat_service_surfaces_real_backend_failure_as_unavailable() -> None:
    service = HarnessChatService(FailingHarness())  # type: ignore[arg-type]

    with pytest.raises(ChatServiceUnavailable, match="retrieval-backed chat harness"):
        await service.answer(
            query="增值税优惠",
            trace_id="trace_1",
            session_id="session_1",
            user_id="user_1",
        )
