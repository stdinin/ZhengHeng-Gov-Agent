from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


class ObservationReason(StrEnum):
    INTENT_ERROR = "INTENT_ERROR"
    RETRIEVAL_ERROR = "RETRIEVAL_ERROR"
    ROUTING_ERROR = "ROUTING_ERROR"
    GENERATION_ERROR = "GENERATION_ERROR"
    CITATION_ERROR = "CITATION_ERROR"
    STALE_POLICY = "STALE_POLICY"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    MEMORY_CONTAMINATION = "MEMORY_CONTAMINATION"
    TIMEOUT = "TIMEOUT"
    SAFETY_BLOCK = "SAFETY_BLOCK"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_PARTIAL_FAILURE = "AGENT_PARTIAL_FAILURE"
    AGGREGATION_ERROR = "AGGREGATION_ERROR"
    CROSS_DEPARTMENT_CONFLICT = "CROSS_DEPARTMENT_CONFLICT"
    UNKNOWN = "UNKNOWN"


class FeedbackType(StrEnum):
    LIKE = "LIKE"
    DISLIKE = "DISLIKE"
    CORRECTION = "CORRECTION"
    FOLLOWUP = "FOLLOWUP"
    REPORT = "REPORT"


class Feedback(BaseModel):
    id: str
    trace_id: str
    user_id: str
    feedback_type: FeedbackType = Field(
        validation_alias=AliasChoices("feedback_type", "type"),
        serialization_alias="type",
    )
    text: str | None = Field(default=None, max_length=4_000)
    created_at: datetime


class BadCaseStatus(StrEnum):
    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class BadCase(BaseModel):
    """A reviewable observation derived from feedback or a failed execution."""

    id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=128)
    reason: ObservationReason
    confidence: float = Field(ge=0, le=1)
    evidence: dict[str, object] = Field(default_factory=dict)
    source: str = Field(min_length=1, max_length=64)
    status: BadCaseStatus = BadCaseStatus.OPEN
    feedback_id: str | None = Field(default=None, max_length=128)
    agent_id: str | None = Field(default=None, max_length=128)
    dept_id: str | None = Field(default=None, max_length=128)
    orchestration_stage: str | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime


class StrategyStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    REPLAY_PASSED = "REPLAY_PASSED"
    SHADOW = "SHADOW"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    GRAY = "GRAY"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ROLLED_BACK = "ROLLED_BACK"


class ActionType(StrEnum):
    QUERY_EXPAND = "QUERY_EXPAND"
    QUERY_REPLACE_TERM = "QUERY_REPLACE_TERM"
    DEPARTMENT_HINT = "DEPARTMENT_HINT"
    TOP_K_ADJUST = "TOP_K_ADJUST"
    RRF_WEIGHT_HINT = "RRF_WEIGHT_HINT"
    RERANK_TOP_N_ADJUST = "RERANK_TOP_N_ADJUST"
    ANSWER_TEMPLATE = "ANSWER_TEMPLATE"
    VERIFY_THRESHOLD_ADJUST = "VERIFY_THRESHOLD_ADJUST"
    TERM_ALIAS = "TERM_ALIAS"


class QueryExpandAction(BaseModel):
    action_type: Literal[ActionType.QUERY_EXPAND] = Field(serialization_alias="type")
    terms: list[str] = Field(min_length=1, max_length=8)


class QueryReplaceTermAction(BaseModel):
    action_type: Literal[ActionType.QUERY_REPLACE_TERM] = Field(serialization_alias="type")
    source_term: str = Field(min_length=1, max_length=128)
    replacement_term: str = Field(min_length=1, max_length=128)


class DepartmentHintAction(BaseModel):
    action_type: Literal[ActionType.DEPARTMENT_HINT] = Field(serialization_alias="type")
    department_id: str = Field(min_length=1, max_length=128)


class TopKAdjustAction(BaseModel):
    action_type: Literal[ActionType.TOP_K_ADJUST] = Field(serialization_alias="type")
    top_k: int | None = Field(default=None, ge=1, le=50)
    dense_top_k: int | None = Field(default=None, ge=1, le=100)
    bm25_top_k: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def validate_target_counts(self) -> TopKAdjustAction:
        if self.top_k is None and (self.dense_top_k is None or self.bm25_top_k is None):
            raise ValueError("TOP_K_ADJUST requires top_k or both dense_top_k and bm25_top_k.")
        return self


class RRFWeightHintAction(BaseModel):
    action_type: Literal[ActionType.RRF_WEIGHT_HINT] = Field(serialization_alias="type")
    bm25_weight: float = Field(ge=0, le=1)
    dense_weight: float = Field(ge=0, le=1)


class RerankTopNAdjustAction(BaseModel):
    action_type: Literal[ActionType.RERANK_TOP_N_ADJUST] = Field(serialization_alias="type")
    top_n: int = Field(ge=1, le=100)


class AnswerTemplateAction(BaseModel):
    action_type: Literal[ActionType.ANSWER_TEMPLATE] = Field(serialization_alias="type")
    template_id: str = Field(min_length=1, max_length=128)


class VerifyThresholdAdjustAction(BaseModel):
    action_type: Literal[ActionType.VERIFY_THRESHOLD_ADJUST] = Field(serialization_alias="type")
    threshold: float = Field(ge=0.7, le=1)


class TermAliasAction(BaseModel):
    action_type: Literal[ActionType.TERM_ALIAS] = Field(serialization_alias="type")
    canonical_term: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(min_length=1, max_length=12)


StrategyAction = Annotated[
    QueryExpandAction
    | QueryReplaceTermAction
    | DepartmentHintAction
    | TopKAdjustAction
    | RRFWeightHintAction
    | RerankTopNAdjustAction
    | AnswerTemplateAction
    | VerifyThresholdAdjustAction
    | TermAliasAction,
    Field(discriminator="action_type"),
]


class StrategyType(StrEnum):
    SKILL = "SKILL"
    HOOK = "HOOK"
    RULE = "RULE"


class StrategyScope(BaseModel):
    mode: Literal["global", "orchestrator", "department"] = "global"
    dept_id: str | None = Field(default=None, max_length=128)
    department_ids: list[str] = Field(default_factory=list, max_length=32)
    intent_types: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_multi_agent_scope(self) -> StrategyScope:
        if self.mode == "department" and not (self.dept_id or self.department_ids):
            raise ValueError("Department strategy scope requires dept_id or department_ids.")
        if self.mode != "department" and self.dept_id is not None:
            raise ValueError("dept_id is valid only for department strategy scope.")
        return self


class StrategyTrigger(BaseModel):
    any_terms: list[str] = Field(default_factory=list, max_length=32)


class StrategyCandidate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    status: StrategyStatus
    strategy_type: StrategyType = Field(
        default=StrategyType.SKILL,
        validation_alias=AliasChoices("strategy_type", "type"),
        serialization_alias="type",
    )
    name: str = Field(default="unnamed-strategy", min_length=1, max_length=256)
    created_by: str = Field(default="reflector", min_length=1, max_length=128)
    approved_by: str | None = Field(default=None, max_length=128)
    approved_at: datetime | None = None
    scope: StrategyScope = Field(default_factory=StrategyScope)
    trigger: StrategyTrigger = Field(default_factory=StrategyTrigger)
    actions: list[StrategyAction] = Field(min_length=1, max_length=16)
    created_from_badcase_ids: list[str] = Field(default_factory=list, max_length=64)
    rollout_percent: int = Field(default=0, ge=0, le=100)
    replay_report_id: str | None = Field(default=None, max_length=128)
    decision_reason: str | None = Field(default=None, max_length=4_000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def normalize_goal_action_shape(cls, value: Any) -> Any:
        """Accept the published DSL's ``type`` key while retaining a safe discriminator."""

        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        actions = normalized.get("actions")
        if not isinstance(actions, list):
            return normalized
        normalized_actions: list[object] = []
        for action in actions:
            if not isinstance(action, dict):
                normalized_actions.append(action)
                continue
            action_value = dict(action)
            if "action_type" not in action_value and "type" in action_value:
                action_value["action_type"] = action_value["type"]
            normalized_actions.append(action_value)
        normalized["actions"] = normalized_actions
        return normalized


class ExperimentBucket(StrEnum):
    CONTROL = "CONTROL"
    TREATMENT = "TREATMENT"


class ReplayMetricSnapshot(BaseModel):
    success_rate: float = Field(ge=0, le=1)
    citation_error_rate: float = Field(ge=0, le=1)
    stale_policy_errors: int = Field(ge=0)
    p95_ms: float = Field(ge=0)


class ReplayReport(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    strategy_id: str = Field(min_length=1, max_length=128)
    strategy_version: int = Field(ge=1)
    baseline: ReplayMetricSnapshot
    candidate: ReplayMetricSnapshot
    target_badcases_resolved: int = Field(ge=0)
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    frozen_input_ids: list[str] = Field(default_factory=list)
    source_trace_ids: list[str] = Field(default_factory=list)
    candidate_trace_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class FrozenReplayInput(BaseModel):
    """Immutable, persisted input captured from a real completed harness trace."""

    id: str = Field(min_length=1, max_length=128)
    strategy_id: str = Field(min_length=1, max_length=128)
    strategy_version: int = Field(ge=1)
    source_trace_id: str = Field(min_length=1, max_length=128)
    source_trace_created_at: datetime
    user_id: str | None = Field(default=None, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4_000)
    normalized_query: str | None = Field(default=None, max_length=4_000)
    rewritten_queries: list[str] = Field(default_factory=list)
    department_routes: list[dict[str, object]] = Field(default_factory=list)
    original_context: list[str] = Field(default_factory=list)
    retrieval_metadata: dict[str, object] = Field(default_factory=dict)
    baseline_status: str = Field(min_length=1, max_length=32)
    baseline_citations: list[dict[str, object]] = Field(default_factory=list)
    baseline_verification: dict[str, object] | None = None
    baseline_errors: list[str] = Field(default_factory=list)
    baseline_timings_ms: dict[str, float] = Field(default_factory=dict)
    baseline_strategy_id: str | None = Field(default=None, max_length=128)
    baseline_strategy_version: int | None = Field(default=None, ge=1)
    created_at: datetime


class StrategyExecution(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    strategy_id: str = Field(min_length=1, max_length=128)
    strategy_version: int = Field(ge=1)
    trace_id: str = Field(min_length=1, max_length=128)
    bucket: ExperimentBucket
    success: bool
    citation_ok: bool
    stale_policy_error: bool = False
    latency_ms: float = Field(ge=0)
    created_at: datetime


class ExperimentStatus(StrEnum):
    MONITORING = "MONITORING"
    ROLLED_BACK = "ROLLED_BACK"
    PROMOTED = "PROMOTED"


class ExperimentRecord(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    strategy_id: str = Field(min_length=1, max_length=128)
    strategy_version: int = Field(ge=1)
    status: ExperimentStatus
    control_n: int = Field(ge=0)
    treatment_n: int = Field(ge=0)
    control: ReplayMetricSnapshot
    treatment: ReplayMetricSnapshot
    decision_reasons: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
