from datetime import UTC, datetime

import httpx

from backend.app.config import Settings
from backend.app.domain.documents import (
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    PolicyStatus,
)
from backend.app.ingestion.lifecycle import LifecycleError
from backend.app.main import create_app


class MissingDocumentRepository:
    async def get_document(self, document_id: str) -> None:
        return None


class RecordingDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.versions: dict[str, DocumentVersion] = {}
        self.chunks_created = 0
        self.ingestions = 0

    async def get_document(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    async def list_documents(self, *, limit: int) -> list[Document]:
        return list(self.documents.values())[:limit]

    async def create_document(self, document: Document) -> None:
        self.documents[document.id] = document

    async def create_version(self, version: DocumentVersion) -> None:
        self.versions[version.id] = version

    async def create_chunks(self, chunks: list[object]) -> None:
        self.chunks_created = len(chunks)

    async def persist_ingested_version(
        self,
        document: Document,
        version: DocumentVersion,
        chunks: list[object],
        *,
        create_document: bool,
    ) -> None:
        self.ingestions += 1
        if create_document:
            await self.create_document(document)
        await self.create_version(version)
        await self.create_chunks(chunks)

    async def list_versions(self, document_id: str) -> list[DocumentVersion]:
        return [version for version in self.versions.values() if version.document_id == document_id]

    async def publish_version(self, version_id: str) -> DocumentVersion:
        version = self.versions[version_id]
        if version.status is not DocumentVersionStatus.READY:
            raise LifecycleError("Only READY versions can be published.")
        published = version.model_copy(update={"status": DocumentVersionStatus.ACTIVE})
        self.versions[version_id] = published
        return published

    async def archive_version(self, version_id: str) -> DocumentVersion:
        version = self.versions[version_id]
        archived = version.model_copy(update={"status": DocumentVersionStatus.ARCHIVED})
        self.versions[version_id] = archived
        return archived


async def test_document_lookup_returns_uniform_not_found_error() -> None:
    app = create_app(
        settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"),
        document_repository=MissingDocumentRepository(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/documents/doc_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_document_list_returns_canonical_documents() -> None:
    now = datetime.now(UTC)
    repository = RecordingDocumentRepository()
    document = Document(
        id="doc_list",
        logical_name="可列出的政策",
        department_id="dept_tax",
        source_type="upload",
        created_at=now,
        updated_at=now,
    )
    repository.documents[document.id] = document
    app = create_app(
        settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"),
        document_repository=repository,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/documents")

    assert response.status_code == 200
    assert response.json()[0]["id"] == document.id


async def test_document_upload_parses_chunks_and_creates_parsed_version() -> None:
    repository = RecordingDocumentRepository()
    app = create_app(
        settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"),
        document_repository=repository,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/documents/upload",
            data={
                "logical_name": "演示政策",
                "department_id": "dept_tax",
                "policy_status": PolicyStatus.FULLY_EFFECTIVE.value,
            },
            files={"file": ("policy.md", "# 演示政策\n\n第一条 示例内容。", "text/markdown")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == DocumentVersionStatus.PARSED
    assert body["chunk_count"] == 1
    assert len(repository.documents) == 1
    assert repository.chunks_created == 1
    assert repository.ingestions == 1


async def test_chinatax_import_normalizes_source_record_and_keeps_version_parsed() -> None:
    repository = RecordingDocumentRepository()
    app = create_app(
        settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"),
        document_repository=repository,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/documents/import/chinatax",
            json={
                "title": "税收演示政策",
                "content": "第一条 公开政策内容。",
                "document_number": "公告2026年第1号",
                "aging": "全文有效",
                "issuing_department": "国家税务总局",
                "url": "https://example.test/policy",
            },
        )

    assert response.status_code == 201
    assert response.json()["status"] == DocumentVersionStatus.PARSED
    document = next(iter(repository.documents.values()))
    assert document.source_dataset == "salpt/chinatax-policy-corpus"
    assert document.source_url == "https://example.test/policy"


async def test_document_version_endpoints_list_publish_and_archive() -> None:
    now = datetime.now(UTC)
    repository = RecordingDocumentRepository()
    document = Document(
        id="doc_1",
        logical_name="演示政策",
        department_id="dept_tax",
        source_type="upload",
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id="ver_1",
        document_id=document.id,
        version_no=1,
        sha256="a" * 64,
        status=DocumentVersionStatus.READY,
        policy_status=PolicyStatus.FULLY_EFFECTIVE,
        title="演示政策",
        raw_text="第一条 示例内容。",
        trace_id="trace_1",
        created_at=now,
        updated_at=now,
    )
    repository.documents[document.id] = document
    repository.versions[version.id] = version
    app = create_app(
        settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"),
        document_repository=repository,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get("/api/v1/documents/doc_1/versions")
        published = await client.post("/api/v1/documents/versions/ver_1/publish")
        archived = await client.post("/api/v1/documents/versions/ver_1/archive")

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "ver_1"
    assert published.status_code == 200
    assert published.json()["status"] == DocumentVersionStatus.ACTIVE
    assert archived.status_code == 200
    assert archived.json()["status"] == DocumentVersionStatus.ARCHIVED


async def test_document_publish_rejects_a_version_not_ready_for_indexed_release() -> None:
    now = datetime.now(UTC)
    repository = RecordingDocumentRepository()
    document = Document(
        id="doc_parsed",
        logical_name="未索引政策",
        department_id="dept_tax",
        source_type="upload",
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id="ver_parsed",
        document_id=document.id,
        version_no=1,
        sha256="b" * 64,
        status=DocumentVersionStatus.PARSED,
        policy_status=PolicyStatus.FULLY_EFFECTIVE,
        title=document.logical_name,
        raw_text="第一条 示例内容。",
        trace_id="trace_parsed",
        created_at=now,
        updated_at=now,
    )
    repository.documents[document.id] = document
    repository.versions[version.id] = version
    app = create_app(
        settings=Settings(app_secret="test-secret-that-is-at-least-32-bytes"),
        document_repository=repository,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/documents/versions/ver_parsed/publish")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_CONFLICT"
