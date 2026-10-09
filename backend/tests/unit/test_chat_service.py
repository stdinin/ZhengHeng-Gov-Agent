from dataclasses import dataclass
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


@dataclass
class ClosableResource:
    close_calls: int = 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_harness_chat_service_surfaces_real_backend_failure_as_unavailable() -> None:
    service = HarnessChatService(FailingHarness())  # type: ignore[arg-type]

    with pytest.raises(ChatServiceUnavailable, match="retrieval-backed chat harness"):
        await service.answer(
            query="增值税优惠",
            trace_id="trace_1",
            session_id="session_1",
            user_id="user_1",
        )


@pytest.mark.asyncio
async def test_harness_chat_service_closes_each_owned_resource_once() -> None:
    resource = ClosableResource()
    service = HarnessChatService(  # type: ignore[arg-type]
        FailingHarness(), resources=(resource, resource)
    )

    await service.close()

    assert resource.close_calls == 1
