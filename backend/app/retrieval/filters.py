from dataclasses import dataclass

from backend.app.domain.documents import DocumentVersionStatus
from backend.app.ingestion.lifecycle import can_be_fact_evidence


@dataclass(frozen=True, slots=True)
class RetrievedFact:
    chunk_id: str
    document_id: str
    version_id: str
    canonical_status: DocumentVersionStatus


def canonical_fact_filter(candidates: list[RetrievedFact]) -> list[RetrievedFact]:
    """Final guard after every retrieval source; memory and stale indexes cannot bypass it."""

    return [
        candidate for candidate in candidates if can_be_fact_evidence(candidate.canonical_status)
    ]
