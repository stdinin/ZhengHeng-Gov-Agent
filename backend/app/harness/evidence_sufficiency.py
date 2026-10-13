"""Deterministic pre-answer checks for whether supplied evidence can support a query.

This module intentionally does not know about evaluation labels, gold chunks, retriever
scores, or expected answers.  It is safe to invoke on the online evidence boundary:
the query plus already canonicalized evidence only.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, Field

from backend.app.harness.citations import Evidence
from backend.app.ingestion.lifecycle import can_be_fact_evidence


class VerifierDecision(StrEnum):
    ANSWER = "ANSWER"
    ABSTAIN = "ABSTAIN"


class EvidenceStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    AMBIGUOUS = "AMBIGUOUS"


class ConstraintStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_REQUESTED = "NOT_REQUESTED"
    AMBIGUOUS = "AMBIGUOUS"


class ConstraintAssessment(BaseModel):
    topic: ConstraintStatus
    entity: ConstraintStatus
    policy_identity: ConstraintStatus
    year_date: ConstraintStatus
    version_batch_ordinal: ConstraintStatus
    core_fact: ConstraintStatus


class EvidenceSufficiencyResult(BaseModel):
    """Machine-parseable result of an evidence-only verification decision."""

    decision: VerifierDecision
    evidence_status: EvidenceStatus
    reason_code: str = Field(min_length=1)
    supporting_chunk_ids: list[str]
    unsupported_constraints: list[str]
    constraints: ConstraintAssessment


_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?:年)?")
_BATCH = re.compile(r"第[一二三四五六七八九十百千万零〇0-9]+批")
_VERSION_MARKERS = (
    re.compile(r"(?:19|20)\d{2}年版"),
    re.compile(r"修正案[（(][一二三四五六七八九十百千万零〇0-9]+[）)]"),
    re.compile(r"[（(](?:试行|暂行)[）)]"),
    re.compile(r"[A-ZＡ-Ｚ]类"),
)
_ENTITY_TERMS = (
    "国家税务总局",
    "财政部",
    "海关总署",
    "国务院",
    "商务部",
    "国家发展改革委",
    "生态环境部",
    "工业和信息化部",
)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[\s《》〈〉【】\[\]（）()、，,。；;：:\"“”'‘’\-—_]", "", normalized)


def _policy_title(query: str) -> str | None:
    """Return the outermost title in a standard ``请依据《…》`` policy query."""

    start = query.find("《")
    end = query.rfind("》")
    if start < 0 or end <= start:
        return None
    title = query[start + 1 : end].strip()
    return title or None


def _extra_core_fact_constraint(query: str) -> str | None:
    """Return any request-specific fact beyond the standard title-summary template."""

    end = query.rfind("》")
    if end < 0:
        return None
    tail = query[end + 1 :].strip()
    if re.fullmatch(r"说明(?:该政策)?(?:的)?主要规定[。！？!?]?", tail):
        return None
    return _normalize(re.sub(r"^说明", "", tail)) or None


def _years(value: str) -> set[str]:
    return {match.group(1) for match in _YEAR.finditer(value)}


def _version_markers(value: str) -> set[str]:
    values = set(_BATCH.findall(value))
    for pattern in _VERSION_MARKERS:
        values.update(pattern.findall(value))
    return {_normalize(item) for item in values}


def _entities(value: str) -> set[str]:
    return {term for term in _ENTITY_TERMS if term in value}


def _bigrams(value: str) -> set[str]:
    normalized = _normalize(value)
    return {normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))}


def _topic_related(query_title: str, evidence: Evidence) -> bool:
    if _normalize(query_title) == _normalize(evidence.title):
        return True
    query_bigrams = _bigrams(query_title)
    evidence_bigrams = _bigrams(f"{evidence.title} {evidence.text}")
    if not query_bigrams or not evidence_bigrams:
        return False
    return len(query_bigrams & evidence_bigrams) / len(query_bigrams) >= 0.35


class EvidenceSufficiencyVerifier:
    """Conservative verifier for identity-bound policy questions.

    The verifier deliberately rejects topic-only matches.  A positive decision
    requires an exact policy-title match in an already active canonical evidence
    item, plus every explicit entity, year, and version/batch constraint found in
    the query title.
    """

    def verify(self, *, query: str, evidence: list[Evidence]) -> EvidenceSufficiencyResult:
        title = _policy_title(query)
        active = [item for item in evidence if can_be_fact_evidence(item.status)]
        if not active:
            return self._insufficient(
                reason_code="NO_ACTIVE_EVIDENCE",
                topic=ConstraintStatus.UNSUPPORTED,
                entity=self._requested_or_not(_entities(title or ""), False),
                policy_identity=(
                    ConstraintStatus.AMBIGUOUS if title is None else ConstraintStatus.UNSUPPORTED
                ),
                year_date=self._requested_or_not(_years(title or ""), False),
                version_batch_ordinal=self._requested_or_not(_version_markers(title or ""), False),
                core_fact=ConstraintStatus.UNSUPPORTED,
            )
        if title is None:
            return self._ambiguous(active)

        normalized_title = _normalize(title)
        matching = [item for item in active if _normalize(item.title) == normalized_title]
        topic = (
            ConstraintStatus.SUPPORTED
            if any(_topic_related(title, item) for item in active)
            else ConstraintStatus.UNSUPPORTED
        )
        requested_entities = _entities(title)
        requested_years = _years(title)
        requested_versions = _version_markers(title)
        requested_core_fact = _extra_core_fact_constraint(query)

        if not matching:
            return self._insufficient(
                reason_code="POLICY_IDENTITY_UNSUPPORTED",
                topic=topic,
                entity=self._constraint_from_any(
                    requested_entities, active, lambda item: _entities(self._evidence_text(item))
                ),
                policy_identity=ConstraintStatus.UNSUPPORTED,
                year_date=self._constraint_from_any(
                    requested_years, active, lambda item: _years(self._evidence_text(item))
                ),
                version_batch_ordinal=self._constraint_from_any(
                    requested_versions,
                    active,
                    lambda item: _version_markers(self._evidence_text(item)),
                ),
                core_fact=ConstraintStatus.UNSUPPORTED,
            )

        entity = self._constraint_from_any(
            requested_entities, matching, lambda item: _entities(self._evidence_text(item))
        )
        year_date = self._constraint_from_any(
            requested_years, matching, lambda item: _years(self._evidence_text(item))
        )
        version = self._constraint_from_any(
            requested_versions,
            matching,
            lambda item: _version_markers(self._evidence_text(item)),
        )
        core_fact = (
            ConstraintStatus.SUPPORTED
            if requested_core_fact is None
            or any(
                requested_core_fact in _normalize(self._evidence_text(item))
                for item in matching
            )
            else ConstraintStatus.UNSUPPORTED
        )
        constraints = ConstraintAssessment(
            topic=ConstraintStatus.SUPPORTED,
            entity=entity,
            policy_identity=ConstraintStatus.SUPPORTED,
            year_date=year_date,
            version_batch_ordinal=version,
            core_fact=core_fact,
        )
        unsupported = self._unsupported(constraints)
        if unsupported:
            reason = self._reason_for(unsupported)
            return EvidenceSufficiencyResult(
                decision=VerifierDecision.ABSTAIN,
                evidence_status=EvidenceStatus.INSUFFICIENT,
                reason_code=reason,
                supporting_chunk_ids=[],
                unsupported_constraints=unsupported,
                constraints=constraints,
            )
        return EvidenceSufficiencyResult(
            decision=VerifierDecision.ANSWER,
            evidence_status=EvidenceStatus.SUFFICIENT,
            reason_code="ALL_REQUIRED_CONSTRAINTS_SUPPORTED",
            supporting_chunk_ids=[item.chunk_id for item in matching],
            unsupported_constraints=[],
            constraints=constraints,
        )

    @staticmethod
    def _evidence_text(item: Evidence) -> str:
        return " ".join(
            value
            for value in (item.title, item.text, item.document_number, item.written_date)
            if value
        )

    @staticmethod
    def _requested_or_not(values: set[str], supported: bool) -> ConstraintStatus:
        if not values:
            return ConstraintStatus.NOT_REQUESTED
        return ConstraintStatus.SUPPORTED if supported else ConstraintStatus.UNSUPPORTED

    def _constraint_from_any(
        self,
        requested: set[str],
        evidence: list[Evidence],
        extractor: Callable[[Evidence], set[str]],
    ) -> ConstraintStatus:
        if not requested:
            return ConstraintStatus.NOT_REQUESTED
        return (
            ConstraintStatus.SUPPORTED
            if any(requested <= extractor(item) for item in evidence)
            else ConstraintStatus.UNSUPPORTED
        )

    def _insufficient(
        self,
        *,
        reason_code: str,
        topic: ConstraintStatus,
        entity: ConstraintStatus,
        policy_identity: ConstraintStatus,
        year_date: ConstraintStatus,
        version_batch_ordinal: ConstraintStatus,
        core_fact: ConstraintStatus,
    ) -> EvidenceSufficiencyResult:
        constraints = ConstraintAssessment(
            topic=topic,
            entity=entity,
            policy_identity=policy_identity,
            year_date=year_date,
            version_batch_ordinal=version_batch_ordinal,
            core_fact=core_fact,
        )
        return EvidenceSufficiencyResult(
            decision=VerifierDecision.ABSTAIN,
            evidence_status=EvidenceStatus.INSUFFICIENT,
            reason_code=reason_code,
            supporting_chunk_ids=[],
            unsupported_constraints=self._unsupported(constraints),
            constraints=constraints,
        )

    def _ambiguous(self, evidence: list[Evidence]) -> EvidenceSufficiencyResult:
        constraints = ConstraintAssessment(
            topic=ConstraintStatus.SUPPORTED if evidence else ConstraintStatus.UNSUPPORTED,
            entity=ConstraintStatus.NOT_REQUESTED,
            policy_identity=ConstraintStatus.AMBIGUOUS,
            year_date=ConstraintStatus.NOT_REQUESTED,
            version_batch_ordinal=ConstraintStatus.NOT_REQUESTED,
            core_fact=ConstraintStatus.AMBIGUOUS,
        )
        return EvidenceSufficiencyResult(
            decision=VerifierDecision.ABSTAIN,
            evidence_status=EvidenceStatus.AMBIGUOUS,
            reason_code="POLICY_IDENTITY_AMBIGUOUS",
            supporting_chunk_ids=[],
            unsupported_constraints=self._unsupported(constraints),
            constraints=constraints,
        )

    @staticmethod
    def _unsupported(constraints: ConstraintAssessment) -> list[str]:
        return [
            name
            for name, value in constraints.model_dump().items()
            if value in {ConstraintStatus.UNSUPPORTED, ConstraintStatus.AMBIGUOUS}
        ]

    @staticmethod
    def _reason_for(unsupported: list[str]) -> str:
        mapping = {
            "entity": "ENTITY_UNSUPPORTED",
            "year_date": "YEAR_DATE_UNSUPPORTED",
            "version_batch_ordinal": "VERSION_BATCH_ORDINAL_UNSUPPORTED",
            "core_fact": "CORE_FACT_UNSUPPORTED",
        }
        return next(
            (mapping[name] for name in unsupported if name in mapping),
            "EVIDENCE_INSUFFICIENT",
        )


__all__ = [
    "ConstraintAssessment",
    "ConstraintStatus",
    "EvidenceStatus",
    "EvidenceSufficiencyResult",
    "EvidenceSufficiencyVerifier",
    "VerifierDecision",
]
