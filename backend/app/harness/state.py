from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field


class AnswerStatus(StrEnum):
    SUCCESS = "SUCCESS"
    ABSTAIN = "ABSTAIN"


class IntentKind(StrEnum):
    POLICY_QUERY = "POLICY_QUERY"
    PROCEDURE_QUERY = "PROCEDURE_QUERY"
    CROSS_DEPT_QUERY = "CROSS_DEPT_QUERY"
    SMALL_TALK = "SMALL_TALK"
    UNSUPPORTED = "UNSUPPORTED"


class IntentEntities(BaseModel):
    location: str | None = None
    dates: list[str] = Field(default_factory=list)
    document_numbers: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    policy_terms: list[str] = Field(default_factory=list)


class IntentDecision(BaseModel):
    intent: IntentKind
    entities: IntentEntities = Field(default_factory=IntentEntities)
    confidence: float = Field(ge=0, le=1)
    used_fallback: bool = False


class RewriteDecision(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)
    used_fallback: bool = False


class DepartmentRoute(BaseModel):
    department_id: str = Field(min_length=1, max_length=128)
    score: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=500)


class RouteDecision(BaseModel):
    routes: list[DepartmentRoute] = Field(min_length=1, max_length=3)
    routing_uncertain: bool = False
    used_fallback: bool = False

    @property
    def department_ids(self) -> list[str]:
        return [route.department_id for route in self.routes]


class AnswerClaim(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    citation_ids: list[str] = Field(min_length=1, max_length=8)


class AnswerCandidate(BaseModel):
    answer: str = Field(min_length=1, max_length=16_000)
    claims: list[AnswerClaim] = Field(default_factory=list)


class ClaimSupport(BaseModel):
    """Schema-constrained semantic validation for one answer claim."""

    supported: bool
    support_score: float = Field(ge=0, le=1)
    contradiction: bool
    reason: str = Field(min_length=1, max_length=1_000)


class AgentState(BaseModel):
    """Explicit request state; nodes exchange typed values instead of free-form dicts."""

    trace_id: str
    user_id: str | None = None
    session_id: str
    raw_query: str
    normalized_query: str | None = None
    intent: IntentDecision | None = None
    rewritten_queries: list[str] = Field(default_factory=list)
    department_routes: RouteDecision | None = None
    memory_context: list[str] = Field(default_factory=list)
    matched_strategies: list[str] = Field(default_factory=list)
    retrieval_hits: list[str] = Field(default_factory=list)
    retrieval_metadata: dict[str, object] = Field(default_factory=dict)
    answer: str | None = None
    citations: list[str] = Field(default_factory=list)
    verification: VerificationResult | None = None
    retry_count: int = Field(default=0, ge=0, le=1)
    status: AnswerStatus | None = None
    errors: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    retryable: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class HarnessResult:
    status: AnswerStatus
    answer: str
    attempts: int
    warnings: list[str] = field(default_factory=list)
