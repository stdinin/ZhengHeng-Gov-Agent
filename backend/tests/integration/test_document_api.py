import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from backend.app.config import Settings
from backend.app.domain.documents import (
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    PolicyStatus,
    SourceType,
)
from backend.app.main import _close_runtime_resources, create_app
from backend.app.storage.document_repository import MongoDocumentRepository

_INFRA_SKIP = "SKIPPED: infrastructure unavailable; set RUN_INTEGRATION=1 after Compose is healthy."


def _require_integration() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip(_INFRA_SKIP)


@pytest.mark.integration
async def test_real_mongo_document_api_uploads_lists_publishes_and_archives() -> None:
    _require_integration()
    settings = Settings(mongo_uri="mongodb://localhost:27017", mongo_db="zhengheng_integration")
    repository = MongoDocumentRepository(settings)
    app = None
    try:
        await repository.initialize_indexes()

        suffix = uuid4().hex
        now = datetime.now(UTC)
        ready_document = Document(
            id=f"doc_api_ready_{suffix}",
            logical_name=f"ready policy {suffix}",
            department_id="dept_tax",
            source_type=SourceType.UPLOAD,
            created_at=now,
            updated_at=now,
        )
        ready_version = DocumentVersion(
            id=f"ver_api_ready_{suffix}",
            document_id=ready_document.id,
            version_no=1,
            sha256=sha256(f"{suffix}:ready".encode()).hexdigest(),
            status=DocumentVersionStatus.READY,
            policy_status=PolicyStatus.FULLY_EFFECTIVE,
            title=ready_document.logical_name,
            raw_text="已完成真实索引前置条件的发布测试版本。",
            trace_id=f"trace_api_{suffix}",
            created_at=now,
            updated_at=now,
        )
        await repository.create_document(ready_document)
        await repository.create_version(ready_version)
        app = create_app(settings=settings, document_repository=repository)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            uploaded = await client.post(
                "/api/v1/documents/upload",
                data={
                    "logical_name": f"uploaded policy {suffix}",
                    "department_id": "dept_tax",
                    "policy_status": PolicyStatus.FULLY_EFFECTIVE.value,
                },
                files={
                    "file": (
                        "policy.md",
                        f"# 标题\n\n第一条 真实 Mongo 上传。{suffix}",
                        "text/markdown",
                    )
                },
            )
            imported = await client.post(
                "/api/v1/documents/import/chinatax",
                json={
                    "title": f"chinatax policy {suffix}",
                    "content": f"第一条 真实 Mongo 数据集导入。{suffix}",
                    "aging": "全文有效",
                    "url": "https://example.test/chinatax-policy",
                },
            )
            versions = await client.get(f"/api/v1/documents/{ready_document.id}/versions")
            published = await client.post(f"/api/v1/documents/versions/{ready_version.id}/publish")
            archived = await client.post(f"/api/v1/documents/versions/{ready_version.id}/archive")
    except (ConnectionFailure, ServerSelectionTimeoutError):
        pytest.skip(_INFRA_SKIP)
    finally:
        # httpx.ASGITransport does not drive FastAPI lifespan automatically.
        # Explicitly close app-owned async Mongo clients before pytest closes
        # the event loop; this is not warning suppression.
        if app is not None:
            await _close_runtime_resources(app)
        else:
            await repository.close()

    assert uploaded.status_code == 201
    assert uploaded.json()["status"] == DocumentVersionStatus.PARSED
    assert imported.status_code == 201
    assert imported.json()["status"] == DocumentVersionStatus.PARSED
    assert versions.status_code == 200
    assert versions.json()[0]["id"] == ready_version.id
    assert published.status_code == 200
    assert published.json()["status"] == DocumentVersionStatus.ACTIVE
    assert archived.status_code == 200
    assert archived.json()["status"] == DocumentVersionStatus.ARCHIVED
