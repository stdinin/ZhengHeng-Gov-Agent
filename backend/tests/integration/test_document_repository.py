import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from backend.app.config import Settings
from backend.app.domain.documents import (
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    PolicyStatus,
    SourceType,
)
from backend.app.storage.document_repository import MongoDocumentRepository


@pytest.mark.integration
async def test_real_mongo_publish_archives_previous_active_version_atomically() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip(
            "SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1 after Compose is healthy."
        )

    now = datetime.now(UTC)
    suffix = uuid4().hex
    document = Document(
        id=f"doc_it_{suffix}",
        logical_name=f"integration policy {suffix}",
        department_id="dept_tax",
        source_type=SourceType.UPLOAD,
        created_at=now,
        updated_at=now,
    )
    first = DocumentVersion(
        id=f"ver_it_{suffix}_1",
        document_id=document.id,
        version_no=1,
        sha256=sha256(f"{suffix}:first".encode()).hexdigest(),
        status=DocumentVersionStatus.READY,
        policy_status=PolicyStatus.FULLY_EFFECTIVE,
        title=document.logical_name,
        raw_text="first version",
        trace_id=f"trace_it_{suffix}",
        created_at=now,
        updated_at=now,
    )
    second = first.model_copy(
        update={
            "id": f"ver_it_{suffix}_2",
            "version_no": 2,
                "sha256": sha256(f"{suffix}:second".encode()).hexdigest(),
            "raw_text": "second version",
        }
    )
    repository = MongoDocumentRepository(
        Settings(mongo_uri="mongodb://localhost:27017", mongo_db="zhengheng_integration")
    )
    await repository.initialize_indexes()
    await repository.create_document(document)
    await repository.create_version(first)
    await repository.create_version(second)

    await repository.publish_version(first.id)
    await repository.publish_version(second.id)

    archived = await repository.get_version(first.id)
    active = await repository.get_version(second.id)
    stored_document = await repository.get_document(document.id)
    assert archived is not None and archived.status is DocumentVersionStatus.ARCHIVED
    assert active is not None and active.status is DocumentVersionStatus.ACTIVE
    assert stored_document is not None and stored_document.current_active_version_id == second.id
