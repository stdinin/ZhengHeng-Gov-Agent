from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from the environment without exposing secrets."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_secret: str = "change-me-before-any-non-local-use"
    api_port: int = 8000
    web_port: int = 5173

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "zhengheng"
    redis_url: str = "redis://localhost:6379/0"
    opensearch_url: str = "http://localhost:9201"
    opensearch_index: str = "policy_chunks"
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str | None = None

    llm_mode: Literal["fake", "remote"] = "fake"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2

    # Retrieval infrastructure is deliberately independent from answer generation:
    # a local/remote embedding model may be available while LLM_MODE remains fake.
    embedding_mode: Literal["local", "remote"] = "local"
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    embedding_timeout_seconds: int = 60

    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_enabled: bool = True
    bm25_top_k: int = 40
    dense_top_k: int = 40
    rrf_k: int = 60
    fused_top_k: int = 60
    rerank_top_n: int = 30
    final_context_top_k: int = 8

    session_ttl_seconds: int = 7_200
    working_memory_ttl_seconds: int = 7_200
    memory_token_budget: int = 2_400

    @model_validator(mode="after")
    def validate_remote_llm(self) -> Self:
        if self.llm_mode == "remote":
            missing = [
                name
                for name, value in (
                    ("LLM_BASE_URL", self.llm_base_url),
                    ("LLM_API_KEY", self.llm_api_key),
                    ("LLM_MODEL", self.llm_model),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"LLM_MODE=remote requires {', '.join(missing)}")
        if self.embedding_mode == "remote":
            missing_embedding = [
                name
                for name, value in (
                    ("EMBEDDING_BASE_URL", self.embedding_base_url),
                    ("EMBEDDING_API_KEY", self.embedding_api_key),
                    ("EMBEDDING_MODEL", self.embedding_model),
                )
                if not value
            ]
            if missing_embedding:
                raise ValueError(
                    "EMBEDDING_MODE=remote requires " + ", ".join(missing_embedding)
                )
        positive_values = {
            "EMBEDDING_DIMENSION": self.embedding_dimension,
            "EMBEDDING_TIMEOUT_SECONDS": self.embedding_timeout_seconds,
            "BM25_TOP_K": self.bm25_top_k,
            "DENSE_TOP_K": self.dense_top_k,
            "RRF_K": self.rrf_k,
            "FUSED_TOP_K": self.fused_top_k,
            "RERANK_TOP_N": self.rerank_top_n,
            "FINAL_CONTEXT_TOP_K": self.final_context_top_k,
        }
        invalid = [name for name, value in positive_values.items() if value <= 0]
        if invalid:
            raise ValueError(f"Positive retrieval settings required: {', '.join(invalid)}")
        return self
