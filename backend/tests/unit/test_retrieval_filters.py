from backend.app.domain.documents import DocumentVersionStatus
from backend.app.retrieval.filters import RetrievedFact, canonical_fact_filter


def test_canonical_fact_filter_removes_archived_and_review_required_candidates() -> None:
    candidates = [
        RetrievedFact("chunk_active", "doc", "ver_active", DocumentVersionStatus.ACTIVE),
        RetrievedFact("chunk_archived", "doc", "ver_archived", DocumentVersionStatus.ARCHIVED),
        RetrievedFact("chunk_review", "doc", "ver_review", DocumentVersionStatus.REVIEW_REQUIRED),
    ]

    filtered = canonical_fact_filter(candidates)

    assert [candidate.chunk_id for candidate in filtered] == ["chunk_active"]
