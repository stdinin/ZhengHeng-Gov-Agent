from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EvalCaseType(StrEnum):
    SINGLE_DEPT = "SINGLE_DEPT"
    CROSS_DEPT = "CROSS_DEPT"
    STALE = "STALE"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"


class EvalCase(BaseModel):
    id: str
    question: str
    gold_department_ids: list[str]
    gold_doc_ids: list[str]
    gold_version_ids: list[str]
    gold_chunk_ids: list[str]
    gold_answer_points: list[str] = Field(default_factory=list)
    case_type: EvalCaseType
    frozen: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalProfile(StrEnum):
    DENSE_ONLY = "dense_only"
    BM25_ONLY = "bm25_only"
    HYBRID_RRF = "hybrid_rrf"
    HYBRID_RRF_RERANK = "hybrid_rrf_rerank"
    HYBRID_RERANK_REWRITE = "hybrid_rerank_rewrite"
    FULL_HARNESS = "full_harness"
