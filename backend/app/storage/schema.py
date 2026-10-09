from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MongoIndex:
    name: str
    keys: tuple[tuple[str, int], ...]
    unique: bool = False
    partial_filter: Mapping[str, object] | None = None


def required_mongo_indexes() -> dict[str, tuple[MongoIndex, ...]]:
    """Canonical indexes required before document ingestion can accept writes."""

    return {
        "departments": (MongoIndex("uq_departments_slug", (("slug", 1),), unique=True),),
        "documents": (
            MongoIndex("ix_documents_department", (("department_id", 1),)),
            MongoIndex("ix_documents_current_version", (("current_active_version_id", 1),)),
        ),
        "document_versions": (
            MongoIndex(
                "uq_versions_document_version", (("document_id", 1), ("version_no", 1)), unique=True
            ),
            MongoIndex("uq_versions_sha256", (("sha256", 1),), unique=True),
            MongoIndex("ix_versions_fact_eligible", (("document_id", 1), ("status", 1))),
            MongoIndex("ix_versions_status", (("status", 1), ("updated_at", -1))),
        ),
        "chunks": (
            MongoIndex(
                "uq_chunks_version_ordinal", (("version_id", 1), ("ordinal", 1)), unique=True
            ),
            MongoIndex("ix_chunks_document_version", (("document_id", 1), ("version_id", 1))),
        ),
    }
