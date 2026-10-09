import httpx
import pytest

from backend.app.config import Settings
from backend.app.llm.base import LLMTokenUsage
from backend.app.llm.openai_compatible import OpenAICompatibleLLM


@pytest.mark.asyncio
async def test_openai_compatible_provider_reports_usage_without_exposing_credentials() -> None:
    captured: list[LLMTokenUsage] = []

    def completion(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "受证据约束的回答"}}],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "total_tokens": 19,
                    "prompt_cache_hit_tokens": 3,
                    "prompt_cache_miss_tokens": 9,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(completion)) as client:
        provider = OpenAICompatibleLLM(
            Settings(
                llm_mode="remote",
                llm_base_url="https://provider.example/v1",
                llm_api_key="test-only-key",
                llm_model="test-model",
            ),
            client=client,
            usage_sink=captured.append,
        )
        assert await provider.text(system="system", user="user") == "受证据约束的回答"

    assert len(captured) == 1
    usage = captured[0]
    assert usage.input_tokens == 12
    assert usage.output_tokens == 7
    assert usage.cached_input_tokens == 3
    assert usage.uncached_input_tokens == 9
    assert "test-only-key" not in repr(usage)
