"""Fail-closed aggregation of already verified department results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from backend.app.agents.models import (
    AggregationPresentation,
    DepartmentAgentResult,
    DepartmentCitation,
    DepartmentExecutionStatus,
)
from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.citations import Citation
from backend.app.ingestion.lifecycle import can_be_fact_evidence
from backend.app.llm.base import LLMClient
from backend.app.runtime.context import RuntimeInvocationAudit

_MARKER = re.compile(r"\[(C\d+)\]")


@dataclass(frozen=True, slots=True)
class AggregatedSection:
    dept_id: str
    content: str
    citation_ids: list[str]


@dataclass(frozen=True, slots=True)
class AggregationResult:
    answer: str
    sections: list[AggregatedSection]
    citations: list[Citation]
    global_verifier_pass: bool
    warnings: list[str]
    runtime_events: list[dict[str, str | float | None]] = field(default_factory=list)
    used_fallback: bool = False


class MultiAgentAggregator:
    """Fail-closed global aggregation with a constrained presentation runtime.

    The semantic runtime may choose the display order of complete, locally
    verified sections.  It cannot produce policy prose: deterministic code
    carries the exact section contents and citation cards into the final answer.
    This means a malformed or unavailable runtime safely falls back without
    widening the factual surface of the response.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    async def aggregate(self, results: list[DepartmentAgentResult]) -> AggregationResult:
        sections: list[AggregatedSection] = []
        citations: list[Citation] = []
        citation_ids_by_identity: dict[tuple[str, str, str], str] = {}
        warnings: list[str] = []

        for result in results:
            if (
                result.status is not DepartmentExecutionStatus.SUCCESS
                or not result.local_verifier_pass
            ):
                continue
            replacement_ids: dict[str, str] = {}
            for source in result.citations:
                citation = self._canonical_citation(source, result.dept_id)
                if citation is None:
                    continue
                identity = (citation.document_id, citation.version_id, citation.chunk_id)
                global_id = citation_ids_by_identity.get(identity)
                if global_id is None:
                    global_id = f"C{len(citations) + 1}"
                    citation_ids_by_identity[identity] = global_id
                    citations.append(replace(citation, id=global_id))
                replacement_ids[source.id] = global_id
            referenced = set(_MARKER.findall(result.answer))
            if not replacement_ids or not referenced.issubset(replacement_ids):
                warnings.append(
                    f"Dropped {result.dept_id} section with unsupported citation markers."
                )
                continue
            content = self._replace_markers(result.answer, replacement_ids)
            sections.append(
                AggregatedSection(
                    dept_id=result.dept_id,
                    content=content,
                    citation_ids=list(dict.fromkeys(replacement_ids.values())),
                )
            )

        runtime_events: list[dict[str, str | float | None]] = []
        used_fallback = False
        sections, ordering_warning, runtime_events, used_fallback = await self._present(sections)
        if ordering_warning is not None:
            warnings.append(ordering_warning)
        answer = "\n\n".join(f"【{section.dept_id}】\n{section.content}" for section in sections)
        verifier_warnings = self._verify(sections, citations, answer)
        warnings.extend(verifier_warnings)
        return AggregationResult(
            answer=answer if not verifier_warnings else "当前有效政策证据不足，暂不作答。",
            sections=sections if not verifier_warnings else [],
            citations=citations if not verifier_warnings else [],
            global_verifier_pass=not verifier_warnings,
            warnings=warnings,
            runtime_events=runtime_events,
            used_fallback=used_fallback,
        )

    async def _present(
        self, sections: list[AggregatedSection]
    ) -> tuple[
        list[AggregatedSection],
        str | None,
        list[dict[str, str | float | None]],
        bool,
    ]:
        """Ask the runtime only for a neutral ordering of verified sections."""

        if self._llm is None or len(sections) < 2:
            return sections, None, [], False
        allowed = [section.dept_id for section in sections]
        try:
            presentation = await self._llm.structured(
                system=(
                    "Choose a neutral display order for the already verified department "
                    "sections. Return only the JSON schema. Do not add, remove, infer, "
                    "or restate policy facts."
                ),
                user=(
                    "departments="
                    + ",".join(allowed)
                    + "\nThe response must contain every department exactly once."
                ),
                schema=AggregationPresentation,
                fixture_name="aggregate",
            )
            runtime_events = self._drain_runtime_events()
            ordered = presentation.ordered_department_ids
            if len(ordered) != len(allowed) or set(ordered) != set(allowed):
                return (
                    sections,
                    "Aggregation presentation output was rejected.",
                    runtime_events,
                    True,
                )
            by_dept = {section.dept_id: section for section in sections}
            return [by_dept[dept_id] for dept_id in ordered], None, runtime_events, False
        except Exception:
            return (
                sections,
                "Aggregation runtime unavailable; kept deterministic verified ordering.",
                self._drain_runtime_events(),
                True,
            )

    def _drain_runtime_events(self) -> list[dict[str, str | float | None]]:
        if self._llm is None:
            return []
        drain = getattr(self._llm, "drain_runtime_audits", None)
        if not callable(drain):
            return []
        return [
            audit.as_trace_metadata()
            for audit in drain()
            if isinstance(audit, RuntimeInvocationAudit)
        ]

    @staticmethod
    def _canonical_citation(source: DepartmentCitation, dept_id: str) -> Citation | None:
        if source.department != dept_id:
            return None
        try:
            status = DocumentVersionStatus(source.status)
        except ValueError:
            return None
        if not can_be_fact_evidence(status):
            return None
        return Citation(
            id=source.id,
            chunk_id=source.chunk_id,
            document_id=source.document_id,
            version_id=source.version_id,
            title=source.title,
            department=source.department,
            status=status,
            excerpt=source.excerpt,
            document_number=source.document_number,
            written_date=source.written_date,
            source_url=source.source_url,
        )

    @staticmethod
    def _verify(
        sections: list[AggregatedSection], citations: list[Citation], answer: str
    ) -> list[str]:
        if not sections or not citations:
            return ["No verified department evidence is available for aggregation."]
        citation_by_id = {citation.id: citation for citation in citations}
        markers = set(_MARKER.findall(answer))
        if markers != set(citation_by_id):
            return ["Global citation cards do not match final answer markers."]
        section_by_dept = {section.dept_id: section for section in sections}
        for citation in citations:
            if not can_be_fact_evidence(citation.status):
                return [f"Citation {citation.id} is not active."]
            section = section_by_dept.get(citation.department)
            if section is None or citation.id not in section.citation_ids:
                return [f"Citation {citation.id} lacks matching department attribution."]
        return []

    @staticmethod
    def _replace_markers(answer: str, replacement_ids: dict[str, str]) -> str:
        def replace_marker(match: re.Match[str]) -> str:
            return f"[{replacement_ids[match.group(1)]}]"

        return _MARKER.sub(replace_marker, answer)
