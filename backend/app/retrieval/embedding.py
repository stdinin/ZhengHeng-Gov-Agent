"""Independent embedding providers for the real dense retrieval path."""

import asyncio
import importlib
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast

import httpx

from backend.app.config import Settings


class EmbeddingProviderError(RuntimeError):
    """The configured embedding provider did not supply a usable query vector."""


class QueryEmbedder(Protocol):
    async def embed(self, query: str) -> list[float]: ...


class SentenceTransformerModel(Protocol):
    def encode(self, sentences: list[str], *, normalize_embeddings: bool) -> Any: ...


def _load_sentence_transformer(model_name: str) -> SentenceTransformerModel:
    try:
        module = importlib.import_module("sentence_transformers")
        transformer_factory = cast(Any, module).SentenceTransformer
        return cast(SentenceTransformerModel, transformer_factory(model_name))
    except (AttributeError, ImportError, OSError, RuntimeError) as error:
        raise EmbeddingProviderError(
            f"Unable to load embedding model {model_name!r}."
        ) from error


class LocalSentenceTransformerEmbedder:
    """Real local BGE-compatible encoder, independent from the chat LLM provider."""

    def __init__(
        self,
        settings: Settings,
        *,
        model_loader: Callable[[str], SentenceTransformerModel] = _load_sentence_transformer,
    ) -> None:
        self._model_name = settings.embedding_model
        self._embedding_dimension = settings.embedding_dimension
        self._model_loader = model_loader
        self._model: SentenceTransformerModel | None = None
        self._model_lock = asyncio.Lock()

    async def embed(self, query: str) -> list[float]:
        if not query.strip():
            raise ValueError("Embedding query must not be blank.")
        model = await self._get_model()
        try:
            raw_vector = await asyncio.to_thread(
                model.encode, [query], normalize_embeddings=True
            )
            vector = _coerce_single_vector(raw_vector)
        except (TypeError, ValueError, OSError, RuntimeError) as error:
            raise EmbeddingProviderError("Local embedding provider is unavailable.") from error
        self._validate_dimension(vector)
        return vector

    async def _get_model(self) -> SentenceTransformerModel:
        async with self._model_lock:
            if self._model is None:
                try:
                    self._model = await asyncio.to_thread(self._model_loader, self._model_name)
                except EmbeddingProviderError:
                    raise
                except Exception as error:
                    raise EmbeddingProviderError(
                        "Local embedding provider is unavailable."
                    ) from error
            return self._model

    def _validate_dimension(self, vector: list[float]) -> None:
        if len(vector) != self._embedding_dimension:
            raise EmbeddingProviderError(
                "Embedding provider returned a vector with a different configured dimension."
            )


class OpenAICompatibleEmbeddingProvider:
    """Real OpenAI-compatible remote embedding endpoint, separate from LLM settings."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings.embedding_mode != "remote":
            raise EmbeddingProviderError("EMBEDDING_MODE must be remote for this provider.")
        if not settings.embedding_base_url or not settings.embedding_api_key:
            raise EmbeddingProviderError("A remote embedding provider must be configured.")
        self._base_url = settings.embedding_base_url.rstrip("/")
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model
        self._embedding_dimension = settings.embedding_dimension
        self._timeout_seconds = settings.embedding_timeout_seconds
        self._transport = transport

    async def embed(self, query: str) -> list[float]:
        if not query.strip():
            raise ValueError("Embedding query must not be blank.")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": query},
                )
            response.raise_for_status()
            payload = response.json()
            raw_vector = payload["data"][0]["embedding"]
            vector = [float(value) for value in raw_vector]
        except (httpx.HTTPError, IndexError, KeyError, TypeError, ValueError) as error:
            raise EmbeddingProviderError("Remote embedding provider is unavailable.") from error
        if not vector:
            raise EmbeddingProviderError("Embedding provider returned an empty vector.")
        if len(vector) != self._embedding_dimension:
            raise EmbeddingProviderError(
                "Embedding provider returned a vector with a different configured dimension."
            )
        return vector


def build_embedding_provider(settings: Settings) -> QueryEmbedder:
    """Choose only the configured embedding provider; LLM_MODE is intentionally irrelevant."""

    if settings.embedding_mode == "remote":
        return OpenAICompatibleEmbeddingProvider(settings)
    return LocalSentenceTransformerEmbedder(settings)


def _coerce_single_vector(raw_vector: Any) -> list[float]:
    """Normalize common sentence-transformers/numpy return values to one float vector."""

    value = raw_vector.tolist() if hasattr(raw_vector, "tolist") else raw_vector
    if isinstance(value, Sequence) and value and isinstance(value[0], Sequence):
        value = value[0]
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("Embedding model returned an invalid vector.")
    return [float(component) for component in value]
