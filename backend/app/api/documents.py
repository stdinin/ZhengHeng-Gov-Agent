from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile, status

from backend.app.api.errors import ApiError
from backend.app.domain.documents import (
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    PolicyStatus,
    SourceType,
)
from backend.app.ingestion.adapters.chinatax import (
    ChinataxAdapterError,
    normalize_chinatax_record,
)
from backend.app.ingestion.chunker import chunk_text
from backend.app.ingestion.indexer import DocumentIndexer, IndexingError
from backend.app.ingestion.lifecycle import LifecycleError, content_sha256
from backend.app.ingestion.parser import ParseError, parse_document
from backend.app.storage.document_repository import DocumentRepositoryError, DocumentStore

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def _repository(request: Request) -> DocumentStore:
    return cast(DocumentStore, request.app.state.document_repository)


def _indexer(request: Request) -> DocumentIndexer:
    return cast(DocumentIndexer, request.app.state.document_indexer)


def _repository_error(error: DocumentRepositoryError) -> ApiError:
    return ApiError(status_code=409, code="DOCUMENT_CONFLICT", message=str(error))


def _chunks_from_text(
    *,
    document_id: str,
    version_id: str,
    text: str,
    trace_id: str,
    now: datetime,
) -> list[Chunk]:
    return [
        Chunk(
            id=draft.id,
            document_id=draft.document_id,
            version_id=draft.version_id,
            ordinal=draft.ordinal,
            text=draft.text,
            heading_path=draft.heading_path,
            char_start=draft.char_start,
            char_end=draft.char_end,
            token_count_estimate=max(1, len(draft.text) // 4),
            trace_id=trace_id,
            created_at=now,
            updated_at=now,
        )
        for draft in chunk_text(document_id=document_id, version_id=version_id, text=text)
    ]


@router.get("", response_model=list[Document])
async def list_documents(request: Request, limit: int = 100) -> list[Document]:
    if not 1 <= limit <= 200:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="limit must be between 1 and 200.",
        )
    return await _repository(request).list_documents(limit=limit)


@router.post("/upload", response_model=DocumentVersion, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    logical_name: Annotated[str, Form(min_length=1)],
    department_id: Annotated[str, Form(min_length=1)],
    policy_status: Annotated[PolicyStatus, Form()] = PolicyStatus.UNKNOWN,
    document_id: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    document_number: Annotated[str | None, Form()] = None,
    issuing_department_raw: Annotated[str | None, Form()] = None,
) -> DocumentVersion:
    """Persist a parsed upload and chunks; indexers must promote it to READY separately."""

    filename = file.filename or ""
    payload = await file.read()
    try:
        parsed = parse_document(filename, payload)
    except ParseError as error:
        raise ApiError(status_code=422, code="DOCUMENT_PARSE_FAILED", message=str(error)) from error

    repository = _repository(request)
    now = datetime.now(UTC)
    trace_id = request.state.trace_id
    existing_document = await repository.get_document(document_id) if document_id else None
    if document_id is not None and existing_document is None:
        raise ApiError(
            status_code=404,
            code="DOCUMENT_NOT_FOUND",
            message=f"Document not found: {document_id}",
        )

    document = existing_document or Document(
        id=f"doc_{uuid4().hex}",
        logical_name=logical_name,
        department_id=department_id,
        source_type=SourceType.UPLOAD,
        created_at=now,
        updated_at=now,
    )
    version_no = len(await repository.list_versions(document.id)) + 1
    version = DocumentVersion(
        id=f"ver_{uuid4().hex}",
        document_id=document.id,
        version_no=version_no,
        sha256=content_sha256(payload),
        status=DocumentVersionStatus.PARSED,
        policy_status=policy_status,
        title=title or logical_name,
        document_number=document_number,
        issuing_department_raw=issuing_department_raw,
        raw_text=parsed.text,
        parse_metadata={"format": parsed.format, "original_filename": filename},
        trace_id=trace_id,
        created_at=now,
        updated_at=now,
    )
    chunks = _chunks_from_text(
        document_id=document.id,
        version_id=version.id,
        text=parsed.text,
        trace_id=trace_id,
        now=now,
    )
    version = version.model_copy(update={"chunk_count": len(chunks)})
    try:
        await repository.persist_ingested_version(
            document,
            version,
            chunks,
            create_document=existing_document is None,
        )
    except DocumentRepositoryError as error:
        raise _repository_error(error) from error
    return version


@router.post(
    "/import/chinatax",
    response_model=DocumentVersion,
    status_code=status.HTTP_201_CREATED,
)
async def import_chinatax_document(
    record: dict[str, Any],
    request: Request,
) -> DocumentVersion:
    """Normalize one ChinaTax source row and persist it as a not-yet-indexed version."""

    try:
        source = normalize_chinatax_record(record)
    except ChinataxAdapterError as error:
        raise ApiError(
            status_code=422,
            code="CHINATAX_IMPORT_INVALID",
            message=str(error),
        ) from error

    now = datetime.now(UTC)
    trace_id = request.state.trace_id
    document = Document(
        id=f"doc_{uuid4().hex}",
        logical_name=source.title,
        department_id="dept_tax",
        source_type=SourceType.DATASET,
        source_dataset=source.source_dataset,
        source_url=source.source_url,
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=f"ver_{uuid4().hex}",
        document_id=document.id,
        version_no=1,
        sha256=source.sha256,
        status=DocumentVersionStatus.PARSED,
        policy_status=source.policy_status,
        title=source.title,
        document_number=source.document_number,
        issuing_department_raw=source.issuing_department,
        written_date=source.written_date,
        channel=source.channel,
        effect_level=source.effect_level,
        raw_text=source.content,
        parse_metadata={
            "source_status": source.status.value,
            "tax_type": source.tax_type,
            "labels": source.labels,
        },
        trace_id=trace_id,
        created_at=now,
        updated_at=now,
    )
    chunks = _chunks_from_text(
        document_id=document.id,
        version_id=version.id,
        text=source.content,
        trace_id=trace_id,
        now=now,
    )
    version = version.model_copy(update={"chunk_count": len(chunks)})
    try:
        await _repository(request).persist_ingested_version(
            document,
            version,
            chunks,
            create_document=True,
        )
    except DocumentRepositoryError as error:
        raise _repository_error(error) from error
    return version


@router.get("/{document_id}/versions", response_model=list[DocumentVersion])
async def list_document_versions(document_id: str, request: Request) -> list[DocumentVersion]:
    if await _repository(request).get_document(document_id) is None:
        raise ApiError(
            status_code=404,
            code="DOCUMENT_NOT_FOUND",
            message=f"Document not found: {document_id}",
        )
    return await _repository(request).list_versions(document_id)


@router.post("/versions/{version_id}/publish", response_model=DocumentVersion)
async def publish_document_version(version_id: str, request: Request) -> DocumentVersion:
    try:
        return await _repository(request).publish_version(version_id)
    except LifecycleError as error:
        raise ApiError(status_code=409, code="DOCUMENT_CONFLICT", message=str(error)) from error
    except DocumentRepositoryError as error:
        if "not found" in str(error).lower():
            raise ApiError(
                status_code=404,
                code="DOCUMENT_VERSION_NOT_FOUND",
                message=str(error),
            ) from error
        raise _repository_error(error) from error


@router.post("/versions/{version_id}/archive", response_model=DocumentVersion)
async def archive_document_version(version_id: str, request: Request) -> DocumentVersion:
    try:
        return await _repository(request).archive_version(version_id)
    except DocumentRepositoryError as error:
        if "not found" in str(error).lower():
            raise ApiError(
                status_code=404,
                code="DOCUMENT_VERSION_NOT_FOUND",
                message=str(error),
            ) from error
        raise _repository_error(error) from error


@router.post("/versions/{version_id}/reindex", response_model=DocumentVersion)
async def reindex_document_version(version_id: str, request: Request) -> DocumentVersion:
    """Index a PARSED/FAILED version in both retrieval planes before publish."""

    try:
        return await _indexer(request).index_version(version_id)
    except IndexingError as error:
        status_code = 404 if "not found" in str(error).lower() else 409
        code = "DOCUMENT_VERSION_NOT_FOUND" if status_code == 404 else "DOCUMENT_INDEX_FAILED"
        raise ApiError(status_code=status_code, code=code, message=str(error)) from error


@router.get("/{document_id}", response_model=Document)
async def get_document(document_id: str, request: Request) -> Document:
    document = await _repository(request).get_document(document_id)
    if document is None:
        raise ApiError(
            status_code=404,
            code="DOCUMENT_NOT_FOUND",
            message=f"Document not found: {document_id}",
        )
    return document
