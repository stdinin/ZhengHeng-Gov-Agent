from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.harness.citations import Citation


class DepartmentAgentDefinition(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    dept_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    enabled: bool = True
    timeout_ms: int = Field(default=12_000, ge=100, le=30_000)
    max_concurrency: int = Field(default=8, ge=1, le=64)


class DepartmentExecutionRequest(BaseModel):
    """Internal contract intentionally lacks any caller-controlled department identity."""

    model_config = ConfigDict(extra="forbid")

    parent_trace_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4_000)
    rewritten_query: str = Field(min_length=1, max_length=4_000)
    user_id: str | None = Field(default=None, max_length=128)
    memory_snapshot: dict[str, object] = Field(default_factory=dict)
    strategy_snapshot: dict[str, object] = Field(default_factory=dict)
    deadline_ms: int = Field(default=12_000, ge=100, le=30_000)


class DepartmentExecutionStatus(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    NO_EVIDENCE = "no_evidence"
    RUNTIME_ERROR = "runtime_error"
    RETRIEVAL_ERROR = "retrieval_error"
    VERIFICATION_FAILED = "verification_failed"


class DepartmentCitation(BaseModel):
    id: str
    chunk_id: str
    document_id: str
    version_id: str
    title: str
    department: str
    status: str
    excerpt: str
    document_number: str | None = None
    written_date: str | None = None
    source_url: str | None = None

    @classmethod
    def from_citation(cls, citation: Citation) -> DepartmentCitation:
        return cls(
            id=citation.id,
            chunk_id=citation.chunk_id,
            document_id=citation.document_id,
            version_id=citation.version_id,
            title=citation.title,
            department=citation.department,
            status=citation.status.value,
            excerpt=citation.excerpt,
            document_number=citation.document_number,
            written_date=citation.written_date,
            source_url=citation.source_url,
        )


class DepartmentAgentResult(BaseModel):
    agent_id: str
    dept_id: str
    status: DepartmentExecutionStatus
    answer: str
    citations: list[DepartmentCitation] = Field(default_factory=list)
    evidence_count: int = Field(ge=0)
    local_verifier_pass: bool
    child_trace_id: str
    latency_ms: float = Field(ge=0)
    runtime_backend: str
    error_code: str | None = None


class MultiAgentRouteDecision(BaseModel):
    """V1.1 route form kept separate from the frozen V1.0 RouteDecision."""

    mode: Literal["single", "multi", "abstain"]
    departments: list[str] = Field(default_factory=list, max_length=3)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)


class AggregationPresentation(BaseModel):
    """A deliberately narrow semantic output for global answer presentation.

    The runtime can order already verified department sections, but it never
    receives authority to add, remove, or rewrite policy claims.  The
    deterministic verifier still assembles the final cited answer.
    """

    ordered_department_ids: list[str] = Field(min_length=1, max_length=3)
