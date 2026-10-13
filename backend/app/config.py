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

    # V1.1 is opt-in: ``legacy`` keeps the V1.0 fixed-DAG composition unchanged.
    agent_runtime_backend: Literal["legacy", "fake", "openai_compatible", "pi"] = "legacy"
    agent_runtime_fallback: Literal["none", "fake", "openai_compatible"] = "none"
    pi_runtime_base_url: str = "http://pi-runtime:8090"
    pi_runtime_timeout_ms: int = 20_000
    pi_runtime_connect_timeout_ms: int = 3_000
    internal_service_token: str | None = None

    # V1.1 reuses one backend image in two least-privilege deployment roles.
    service_role: Literal["orchestrator", "department_agent"] = "orchestrator"
    dept_id: str | None = None
    agent_id: str = "orchestrator"
    multi_agent_max_departments: int = 3
    orchestrator_max_parallel: int = 4
    department_agent_timeout_ms: int = 12_000
    department_agents_json: str | None = None
    multi_agent_enabled: bool = False
    agent_execution_mode: Literal["single", "multi"] = "single"
    department_agent_tax_url: str = "http://localhost:8101"
    department_agent_hrss_url: str = "http://localhost:8102"
    department_agent_housing_url: str = "http://localhost:8103"

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
        if self.agent_runtime_backend == "pi" and not self.internal_service_token:
            raise ValueError("AGENT_RUNTIME_BACKEND=pi requires INTERNAL_SERVICE_TOKEN")
        if self.agent_runtime_fallback == "openai_compatible" and self.llm_mode != "remote":
            raise ValueError(
                "AGENT_RUNTIME_FALLBACK=openai_compatible requires LLM_MODE=remote"
            )
        if self.service_role == "department_agent":
            if not self.dept_id:
                raise ValueError("SERVICE_ROLE=department_agent requires DEPT_ID")
            if self.agent_id == "orchestrator":
                raise ValueError("SERVICE_ROLE=department_agent requires a department AGENT_ID")
        positive_values = {
            "EMBEDDING_DIMENSION": self.embedding_dimension,
            "EMBEDDING_TIMEOUT_SECONDS": self.embedding_timeout_seconds,
            "BM25_TOP_K": self.bm25_top_k,
            "DENSE_TOP_K": self.dense_top_k,
            "RRF_K": self.rrf_k,
            "FUSED_TOP_K": self.fused_top_k,
            "RERANK_TOP_N": self.rerank_top_n,
            "FINAL_CONTEXT_TOP_K": self.final_context_top_k,
            "PI_RUNTIME_TIMEOUT_MS": self.pi_runtime_timeout_ms,
            "PI_RUNTIME_CONNECT_TIMEOUT_MS": self.pi_runtime_connect_timeout_ms,
            "MULTI_AGENT_MAX_DEPARTMENTS": self.multi_agent_max_departments,
            "ORCHESTRATOR_MAX_PARALLEL": self.orchestrator_max_parallel,
            "DEPARTMENT_AGENT_TIMEOUT_MS": self.department_agent_timeout_ms,
        }
        invalid = [name for name, value in positive_values.items() if value <= 0]
        if invalid:
            raise ValueError(f"Positive retrieval settings required: {', '.join(invalid)}")
        return self
