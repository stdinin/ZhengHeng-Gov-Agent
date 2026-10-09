from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.domain.documents import DocumentVersionStatus, PolicyStatus
from backend.app.ingestion.lifecycle import classify_aging, content_sha256

CHINATAX_DATASET_ID = "salpt/chinatax-policy-corpus"


class ChinataxAdapterError(ValueError):
    """The source row lacks a field required for a reproducible policy import."""


@dataclass(frozen=True, slots=True)
class ChinataxPolicy:
    title: str
    content: str
    document_number: str | None
    channel: str | None
    effect_level: str | None
    tax_type: str | None
    labels: str | None
    issuing_department: str | None
    written_date: str | None
    source_url: str | None
    source_dataset: str
    sha256: str
    status: DocumentVersionStatus
    policy_status: PolicyStatus


def _required_text(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ChinataxAdapterError(f"chinatax row requires non-empty {field_name!r}.")
    return value.strip()


def _optional_text(record: Mapping[str, Any], field_name: str) -> str | None:
    value = record.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ChinataxAdapterError(f"chinatax {field_name!r} must be text when present.")
    return value.strip() or None


def normalize_chinatax_record(record: Mapping[str, Any]) -> ChinataxPolicy:
    """Validate one public source row without guessing any undocumented field names."""

    title = _required_text(record, "title")
    content = _required_text(record, "content")
    classification = classify_aging(_optional_text(record, "aging"))
    return ChinataxPolicy(
        title=title,
        content=content,
        document_number=_optional_text(record, "document_number"),
        channel=_optional_text(record, "channel"),
        effect_level=_optional_text(record, "effect_level"),
        tax_type=_optional_text(record, "tax_type"),
        labels=_optional_text(record, "labels"),
        issuing_department=_optional_text(record, "issuing_department"),
        written_date=_optional_text(record, "written_date"),
        source_url=_optional_text(record, "url"),
        source_dataset=CHINATAX_DATASET_ID,
        sha256=content_sha256(content.encode("utf-8")),
        status=classification.version_status,
        policy_status=classification.policy_status,
    )
