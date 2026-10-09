from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.domain.documents import (
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    SourceType,
)


def test_canonical_document_objects_keep_identity_lifecycle_and_traceability() -> None:
    now = datetime.now(UTC)
    document = Document(
        id="doc_tax_001",
        logical_name="示例税收政策",
        department_id="dept_tax",
        source_type=SourceType.DATASET,
        source_dataset="fixture-dataset",
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id="ver_tax_001_v1",
        document_id=document.id,
        version_no=1,
        sha256="a" * 64,
        status=DocumentVersionStatus.READY,
        title=document.logical_name,
        raw_text="第一条 示例内容",
        created_at=now,
        updated_at=now,
        trace_id="trace_ingest_001",
    )
    chunk = Chunk(
        id="chunk_tax_001_v1_0001",
        document_id=document.id,
        version_id=version.id,
        ordinal=1,
        text="第一条 示例内容",
        heading_path=["第一章"],
        created_at=now,
        updated_at=now,
        trace_id="trace_ingest_001",
    )

    assert document.current_active_version_id is None
    assert version.trace_id == chunk.trace_id
    assert chunk.version_id == version.id


def test_version_rejects_update_time_before_creation() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="updated_at"):
        DocumentVersion(
            id="ver_time",
            document_id="doc_time",
            version_no=1,
            sha256="b" * 64,
            status=DocumentVersionStatus.READY,
            title="时间校验",
            raw_text="内容",
            trace_id="trace_time",
            created_at=now,
            updated_at=now.replace(year=now.year - 1),
        )
