from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SourceType(StrEnum):
    DATASET = "dataset"
    UPLOAD = "upload"
    WEB = "web"


class DocumentVersionStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    INDEXING = "INDEXING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    ACTIVE_WITH_WARNING = "ACTIVE_WITH_WARNING"
    ARCHIVED = "ARCHIVED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


class PolicyStatus(StrEnum):
    FULLY_EFFECTIVE = "FULLY_EFFECTIVE"
    PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
    REPEALED = "REPEALED"
    UNKNOWN = "UNKNOWN"


class Department(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    description: str = ""
    active: bool = True
    routing_terms: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class Document(BaseModel):
    id: str = Field(min_length=1)
    logical_name: str = Field(min_length=1)
    department_id: str = Field(min_length=1)
    source_type: SourceType
    source_dataset: str | None = None
    source_url: str | None = None
    current_active_version_id: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentVersion(BaseModel):
    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    version_no: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: DocumentVersionStatus
    policy_status: PolicyStatus = PolicyStatus.UNKNOWN
    title: str = Field(min_length=1)
    document_number: str | None = None
    issuing_department_raw: str | None = None
    written_date: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    channel: str | None = None
    effect_level: str | None = None
    raw_text: str = Field(min_length=1)
    parse_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    chunk_count: int = Field(default=0, ge=0)
    indexed_at: datetime | None = None
    trace_id: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def updated_after_created(cls, updated_at: datetime, info: object) -> datetime:
        data = getattr(info, "data", {})
        created_at = data.get("created_at")
        if isinstance(created_at, datetime) and updated_at < created_at:
            raise ValueError("updated_at must be greater than or equal to created_at")
        return updated_at


class Chunk(BaseModel):
    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    ordinal: int = Field(gt=0)
    text: str = Field(min_length=1)
    heading_path: list[str] = Field(default_factory=list)
    char_start: int = Field(default=0, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    token_count_estimate: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    trace_id: str = Field(min_length=1)
