import re
from dataclasses import dataclass

from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.state import AnswerClaim, VerificationResult
from backend.app.ingestion.lifecycle import can_be_fact_evidence


@dataclass(frozen=True, slots=True)
class Evidence:
    chunk_id: str
    document_id: str
    version_id: str
    title: str
    department: str
    status: DocumentVersionStatus
    text: str
    document_number: str | None = None
    written_date: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    id: str
    chunk_id: str
    title: str
    department: str
    status: DocumentVersionStatus
    excerpt: str
    document_number: str | None = None
    written_date: str | None = None
    source_url: str | None = None
    document_id: str = ""
    version_id: str = ""


class CitationError(ValueError):
    """An answer cannot be cited because it has no currently eligible evidence."""


_CITATION_MARKER = re.compile(r"\[(C\d+)\]")
_DOCUMENT_NUMBER = re.compile(
    r"(?P<number>[\u4e00-\u9fffA-Za-z0-9_-]{1,30}?[〔\[]\d{4}[〕\]]\d{1,6}号)"
)


def render_cited_answer(
    answer: str,
    evidence: list[Evidence],
    *,
    claims: list[AnswerClaim] | None = None,
) -> tuple[str, list[Citation]]:
    """Render only evidence explicitly assigned to answer claims.

    Citation identifiers are derived from the eligible retrieval order.  A claim
    may reference any of them, but unrelated context must not become a citation
    card merely because it was retrieved.
    """

    active_evidence = [item for item in evidence if can_be_fact_evidence(item.status)]
    if not active_evidence:
        raise CitationError("No active policy evidence is available for a factual answer.")
    citations_by_id = {
        f"C{index}": Citation(
            id=f"C{index}",
            chunk_id=item.chunk_id,
            document_id=item.document_id,
            version_id=item.version_id,
            title=item.title,
            department=item.department,
            status=item.status,
            excerpt=item.text[:500],
            document_number=item.document_number,
            written_date=item.written_date,
            source_url=item.source_url,
        )
        for index, item in enumerate(active_evidence, start=1)
    }
    selected_ids: list[str]
    if claims is None:
        selected_ids = list(citations_by_id)
    else:
        if not claims:
            raise CitationError("A factual answer must contain at least one cited claim.")
        selected_ids = []
        for claim in claims:
            if not claim.citation_ids:
                raise CitationError(f"Claim has no citations: {claim.text[:80]}")
            for citation_id in claim.citation_ids:
                if citation_id not in citations_by_id:
                    raise CitationError(
                        f"Claim references unavailable citation: {citation_id}."
                    )
                if citation_id not in selected_ids:
                    selected_ids.append(citation_id)
    citations = [citations_by_id[citation_id] for citation_id in selected_ids]
    missing_markers = [
        f"[{citation.id}]" for citation in citations if f"[{citation.id}]" not in answer
    ]
    return f"{answer.strip()} {' '.join(missing_markers)}".strip(), citations


class CitationCheck:
    """Ensure final citations map to current canonical evidence, not stale retrieval or memory."""

    def validate(
        self,
        answer: str,
        citations: list[Citation],
        evidence: list[Evidence],
        *,
        claims: list[AnswerClaim] | None = None,
    ) -> VerificationResult:
        warnings: list[str] = []
        evidence_by_chunk = {item.chunk_id: item for item in evidence}
        active_evidence = [item for item in evidence if can_be_fact_evidence(item.status)]
        expected_by_id = {
            f"C{index}": item for index, item in enumerate(active_evidence, start=1)
        }
        seen_ids: set[str] = set()
        cited_warning_evidence = False
        for item in evidence:
            if not can_be_fact_evidence(item.status):
                warnings.append(f"Evidence chunk {item.chunk_id} has status {item.status.value}.")
        for citation in citations:
            if citation.id in seen_ids:
                warnings.append(f"Citation {citation.id} is duplicated.")
                continue
            seen_ids.add(citation.id)
            source = evidence_by_chunk.get(citation.chunk_id)
            if source is None:
                warnings.append(f"Citation {citation.id} does not map to retrieved evidence.")
                continue
            expected = expected_by_id.get(citation.id)
            if expected is None or expected.chunk_id != citation.chunk_id:
                warnings.append(
                    f"Citation {citation.id} does not match the retrieved evidence order."
                )
            if not can_be_fact_evidence(source.status):
                warnings.append(
                    f"Citation {citation.id} references {source.status.value} evidence."
                )
            if source.status is DocumentVersionStatus.ACTIVE_WITH_WARNING:
                cited_warning_evidence = True
            if f"[{citation.id}]" not in answer:
                warnings.append(f"Citation marker [{citation.id}] is absent from the answer.")
        if not citations:
            warnings.append("Factual answer has no citations.")
        if cited_warning_evidence and "部分失效/时效性警告" not in answer:
            warnings.append("ACTIVE_WITH_WARNING evidence requires a 部分失效/时效性警告.")
        marker_ids = set(_CITATION_MARKER.findall(answer))
        unknown_markers = sorted(marker_ids - seen_ids)
        if unknown_markers:
            warnings.append(
                "Answer contains citation markers without cards: " + ", ".join(unknown_markers)
            )
        known_document_numbers = {
            item.document_number for item in evidence if item.document_number is not None
        }
        for match in _DOCUMENT_NUMBER.finditer(answer):
            mentioned_number = match.group("number")
            if not any(number in mentioned_number for number in known_document_numbers):
                warnings.append(
                    "Document number is absent from retrieved evidence: " + mentioned_number
                )
        if claims is not None:
            referenced_ids: list[str] = []
            if not claims:
                warnings.append("Factual answer has no claims.")
            for claim in claims:
                if not claim.citation_ids:
                    warnings.append(f"Claim has no citations: {claim.text[:80]}")
                for citation_id in claim.citation_ids:
                    if citation_id not in referenced_ids:
                        referenced_ids.append(citation_id)
                    if citation_id not in seen_ids:
                        warnings.append(
                            f"Claim references unknown citation: {citation_id}."
                        )
            if set(referenced_ids) != seen_ids:
                warnings.append(
                    "Citation cards must match the citations declared by answer claims."
                )
        return VerificationResult(passed=not warnings, retryable=True, warnings=warnings)
