import httpx
import pytest
from pydantic import BaseModel, ValidationError

from backend.app.config import Settings


class IntentPayload(BaseModel):
    intent: str


def test_pi_runtime_requires_a_service_token() -> None:
    with pytest.raises(ValidationError, match="INTERNAL_SERVICE_TOKEN"):
        Settings(agent_runtime_backend="pi", internal_service_token=None)


def test_runtime_factory_selects_pi_with_explicit_deterministic_fallback() -> None:
    from backend.app.runtime.fake import FakeRuntime
    from backend.app.runtime.registry import FallbackAgentRuntime, build_agent_runtime

    runtime = build_agent_runtime(
        Settings(
            agent_runtime_backend="pi",
            agent_runtime_fallback="fake",
            internal_service_token="test-internal-service-token",
        )
    )

    assert isinstance(runtime, FallbackAgentRuntime)
    assert isinstance(runtime.fallback, FakeRuntime)


@pytest.mark.asyncio
async def test_openai_compatible_runtime_returns_schema_validated_result() -> None:
    from backend.app.runtime.base import RuntimeMessage, RuntimeNode
    from backend.app.runtime.openai_compatible import OpenAICompatibleRuntime

    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"intent":"POLICY_QUERY"}'}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runtime = OpenAICompatibleRuntime(
            Settings(
                llm_mode="remote",
                llm_base_url="https://provider.example/v1",
                llm_api_key="test-only-key",
                llm_model="test-model",
                agent_runtime_backend="openai_compatible",
            ),
            client=client,
        )
        result = await runtime.invoke(
            node=RuntimeNode.INTENT,
            agent_id="orchestrator",
            dept_id=None,
            trace_id="trace-runtime-openai",
            system_prompt="classify",
            messages=[RuntimeMessage(role="user", content="税收优惠")],
            response_model=IntentPayload,
            timeout_ms=1_000,
        )

    assert result.output.intent == "POLICY_QUERY"
    assert result.backend_requested == "openai_compatible"
    assert result.backend_used == "openai_compatible"
    assert result.total_tokens is None
    assert "test-only-key" not in str(observed["body"])
