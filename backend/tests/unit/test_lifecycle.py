import pytest

from backend.app.domain.documents import DocumentVersionStatus, PolicyStatus
from backend.app.ingestion.lifecycle import (
    LifecycleError,
    can_be_fact_evidence,
    classify_aging,
    content_sha256,
    ensure_publishable,
)


@pytest.mark.parametrize(
    ("aging", "version_status", "policy_status"),
    [
        ("全文有效", DocumentVersionStatus.ACTIVE, PolicyStatus.FULLY_EFFECTIVE),
        ("部分失效", DocumentVersionStatus.ACTIVE_WITH_WARNING, PolicyStatus.PARTIALLY_EFFECTIVE),
        ("全文废止", DocumentVersionStatus.ARCHIVED, PolicyStatus.REPEALED),
        ("失效/废止", DocumentVersionStatus.ARCHIVED, PolicyStatus.REPEALED),
        (None, DocumentVersionStatus.REVIEW_REQUIRED, PolicyStatus.UNKNOWN),
        ("无法确认", DocumentVersionStatus.REVIEW_REQUIRED, PolicyStatus.UNKNOWN),
    ],
)
def test_aging_status_is_mapped_without_defaulting_unknown_to_active(
    aging: str | None, version_status: DocumentVersionStatus, policy_status: PolicyStatus
) -> None:
    result = classify_aging(aging)

    assert result.version_status is version_status
    assert result.policy_status is policy_status


def test_content_sha256_is_deterministic_and_content_sensitive() -> None:
    assert content_sha256(b"same content") == content_sha256(b"same content")
    assert content_sha256(b"same content") != content_sha256(b"changed content")


def test_only_ready_versions_can_be_published() -> None:
    ensure_publishable(DocumentVersionStatus.READY)

    with pytest.raises(LifecycleError, match="READY"):
        ensure_publishable(DocumentVersionStatus.PARSED)


def test_archived_and_review_versions_are_never_fact_evidence() -> None:
    assert can_be_fact_evidence(DocumentVersionStatus.ACTIVE) is True
    assert can_be_fact_evidence(DocumentVersionStatus.ACTIVE_WITH_WARNING) is True
    assert can_be_fact_evidence(DocumentVersionStatus.ARCHIVED) is False
    assert can_be_fact_evidence(DocumentVersionStatus.REVIEW_REQUIRED) is False
