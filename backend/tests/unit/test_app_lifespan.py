from dataclasses import dataclass

import pytest

from backend.app.config import Settings
from backend.app.main import create_app


@dataclass
class ClosableResource:
    close_calls: int = 0

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_application_shutdown_closes_owned_runtime_resources() -> None:
    resources = [ClosableResource() for _ in range(6)]
    app = create_app(
        settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"),
        user_store=resources[0],  # type: ignore[arg-type]
        document_repository=resources[1],  # type: ignore[arg-type]
        document_indexer=resources[2],
        chat_service=resources[3],  # type: ignore[arg-type]
        memory_repository=resources[4],  # type: ignore[arg-type]
        trace_store=resources[5],  # type: ignore[arg-type]
        evolution_repository=ClosableResource(),  # type: ignore[arg-type]
        evolution_service=object(),  # type: ignore[arg-type]
        feedback_service=object(),  # type: ignore[arg-type]
    )
    evolution_resource = app.state.evolution_repository

    async with app.router.lifespan_context(app):
        pass

    assert [resource.close_calls for resource in resources] == [1, 1, 1, 1, 1, 1]
    assert evolution_resource.close_calls == 1
