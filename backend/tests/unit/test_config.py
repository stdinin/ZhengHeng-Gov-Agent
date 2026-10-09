import pytest
from pydantic import ValidationError

from backend.app.config import Settings


def test_local_development_defaults_target_host_published_compose_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "MONGO_URI",
        "REDIS_URL",
        "OPENSEARCH_URL",
        "OPENSEARCH_INDEX",
        "MILVUS_HOST",
        "MILVUS_PORT",
        "MILVUS_COLLECTION",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.mongo_uri == "mongodb://localhost:27017"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.opensearch_url == "http://localhost:9201"
    assert settings.opensearch_index == "policy_chunks"
    assert settings.milvus_host == "localhost"
    assert settings.milvus_port == 19530
    assert settings.milvus_collection is None


def test_retrieval_index_names_can_target_an_existing_canonical_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENSEARCH_INDEX", "policy_chunks_public_eval_v1")
    monkeypatch.setenv("MILVUS_COLLECTION", "policy_chunks_public_eval_v1")

    settings = Settings()

    assert settings.opensearch_index == "policy_chunks_public_eval_v1"
    assert settings.milvus_collection == "policy_chunks_public_eval_v1"


def test_remote_llm_requires_base_url_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "remote")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_fake_llm_mode_does_not_require_remote_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "fake")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    assert Settings().llm_mode == "fake"


def test_fake_llm_can_use_an_independently_configured_remote_embedding_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding settings must not be coupled to the answer-generation provider."""

    monkeypatch.setenv("LLM_MODE", "fake")
    monkeypatch.setenv("EMBEDDING_MODE", "remote")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embeddings.example.invalid/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-only-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1024")

    settings = Settings()

    assert settings.llm_mode == "fake"
    assert settings.embedding_mode == "remote"
    assert settings.embedding_base_url == "https://embeddings.example.invalid/v1"
    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.embedding_dimension == 1024


def test_retrieval_defaults_match_the_fixed_hybrid_caps_and_cross_encoder() -> None:
    settings = Settings()

    assert settings.reranker_model == "BAAI/bge-reranker-v2-m3"
    assert settings.reranker_enabled is True
    assert settings.bm25_top_k == 40
    assert settings.dense_top_k == 40
    assert settings.fused_top_k == 60
    assert settings.rerank_top_n == 30
    assert settings.final_context_top_k == 8
