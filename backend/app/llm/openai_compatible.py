import json
from typing import Any

import httpx
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.llm.base import StructuredModel


class RemoteLLMError(RuntimeError):
    """An OpenAI-compatible provider failed without producing a valid candidate."""


class OpenAICompatibleLLM:
    """OpenAI-compatible client restricted to temperature-zero text and JSON-schema candidates."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        if settings.llm_mode != "remote":
            raise ValueError("OpenAICompatibleLLM requires LLM_MODE=remote.")
        self._base_url = (settings.llm_base_url or "").rstrip("/")
        self._api_key = settings.llm_api_key or ""
        self._model = settings.llm_model or ""
        self._timeout = settings.llm_timeout_seconds
        self._client = client or httpx.AsyncClient(timeout=self._timeout)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[StructuredModel],
        fixture_name: str | None = None,
    ) -> StructuredModel:
        del fixture_name
        body = self._request_body(system, user)
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "strict": True,
                "schema": schema.model_json_schema(),
            },
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                content = await self._chat_completion(body)
                return schema.model_validate_json(content)
            except (RemoteLLMError, ValidationError, json.JSONDecodeError) as error:
                last_error = error
        raise RemoteLLMError(
            "Structured provider response failed JSON schema validation."
        ) from last_error

    async def text(self, *, system: str, user: str, fixture_name: str | None = None) -> str:
        del fixture_name
        return await self._chat_completion(self._request_body(system, user))

    def _request_body(self, system: str, user: str) -> dict[str, Any]:
        return {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    async def _chat_completion(self, body: dict[str, Any]) -> str:
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
                timeout=self._timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise RemoteLLMError("OpenAI-compatible provider request failed.") from error
        if not isinstance(content, str):
            raise RemoteLLMError("OpenAI-compatible provider returned non-text content.")
        return content
