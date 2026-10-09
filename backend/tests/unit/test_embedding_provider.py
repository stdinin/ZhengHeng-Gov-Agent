import httpx
import pytest

from backend.app.config import Settings
from backend.app.retrieval.embedding import (
    EmbeddingProviderError,
    LocalSentenceTransformerEmbedder,
    OpenAICompatibleEmbeddingProvider,
)


@pytest.mark.asyncio
async def test_embedding_network_failures_are_exposed_as_a_domain_error() -> None:
    def unavailable(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = OpenAICompatibleEmbeddingProvider(
        Settings(
            llm_mode="fake",
            embedding_mode="remote",
            embedding_base_url="https://embeddings.example.invalid/v1",
            embedding_api_key="test-only-key",
            embedding_model="BAAI/bge-m3",
        ),
        transport=httpx.MockTransport(unavailable),
    )

    with pytest.raises(EmbeddingProviderError, match="unavailable"):
        await provider.embed("小规模纳税人增值税优惠")


@pytest.mark.asyncio
async def test_embedding_provider_rejects_a_vector_with_the_wrong_configured_dimension() -> None:
    def wrong_dimension(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    provider = OpenAICompatibleEmbeddingProvider(
        Settings(
            llm_mode="fake",
            embedding_mode="remote",
            embedding_base_url="https://embeddings.example.invalid/v1",
            embedding_api_key="test-only-key",
            embedding_model="BAAI/bge-m3",
            embedding_dimension=3,
        ),
        transport=httpx.MockTransport(wrong_dimension),
    )

    with pytest.raises(EmbeddingProviderError, match="dimension"):
        await provider.embed("小规模纳税人增值税优惠")


@pytest.mark.asyncio
async def test_fake_llm_mode_can_use_the_independent_local_embedding_provider() -> None:
    class TestSentenceTransformer:
        def encode(self, sentences: list[str], *, normalize_embeddings: bool) -> list[list[float]]:
            assert sentences == ["小规模纳税人增值税优惠"]
            assert normalize_embeddings is True
            return [[1.0, 0.0, 0.0]]

    embedder = LocalSentenceTransformerEmbedder(
        Settings(llm_mode="fake", embedding_mode="local", embedding_dimension=3),
        model_loader=lambda _: TestSentenceTransformer(),
    )

    assert await embedder.embed("小规模纳税人增值税优惠") == [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_local_embedding_model_load_failures_are_exposed_as_domain_errors() -> None:
    def unavailable(_: str) -> object:
        raise OSError("network unavailable")

    embedder = LocalSentenceTransformerEmbedder(
        Settings(llm_mode="fake", embedding_mode="local", embedding_dimension=3),
        model_loader=unavailable,  # type: ignore[arg-type]
    )

    with pytest.raises(EmbeddingProviderError, match="unavailable"):
        await embedder.embed("小规模纳税人增值税优惠")
