from dataclasses import dataclass
from hashlib import sha256

from backend.app.domain.documents import DocumentVersionStatus, PolicyStatus


class LifecycleError(ValueError):
    """Raised when a document version transition violates governance rules."""


@dataclass(frozen=True, slots=True)
class AgingClassification:
    version_status: DocumentVersionStatus
    policy_status: PolicyStatus


_AGING_MAPPING = {
    "全文有效": AgingClassification(DocumentVersionStatus.ACTIVE, PolicyStatus.FULLY_EFFECTIVE),
    "部分失效": AgingClassification(
        DocumentVersionStatus.ACTIVE_WITH_WARNING, PolicyStatus.PARTIALLY_EFFECTIVE
    ),
    "全文废止": AgingClassification(DocumentVersionStatus.ARCHIVED, PolicyStatus.REPEALED),
    "失效/废止": AgingClassification(DocumentVersionStatus.ARCHIVED, PolicyStatus.REPEALED),
}
_UNKNOWN_AGING = AgingClassification(DocumentVersionStatus.REVIEW_REQUIRED, PolicyStatus.UNKNOWN)


def classify_aging(aging: str | None) -> AgingClassification:
    if aging is None:
        return _UNKNOWN_AGING
    return _AGING_MAPPING.get(aging.strip(), _UNKNOWN_AGING)


def content_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


def ensure_publishable(status: DocumentVersionStatus) -> None:
    if status is not DocumentVersionStatus.READY:
        raise LifecycleError(f"Only READY versions can be published; got {status.value}.")


def can_be_fact_evidence(status: DocumentVersionStatus) -> bool:
    return status in {
        DocumentVersionStatus.ACTIVE,
        DocumentVersionStatus.ACTIVE_WITH_WARNING,
    }
