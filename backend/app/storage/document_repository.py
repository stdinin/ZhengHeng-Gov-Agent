from datetime import UTC, datetime
from typing import Any, Protocol

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from backend.app.config import Settings
from backend.app.domain.documents import (
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    PolicyStatus,
)
from backend.app.harness.citations import Evidence
from backend.app.ingestion.lifecycle import ensure_publishable
from backend.app.retrieval.rrf import RankedCandidate
from backend.app.storage.schema import MongoIndex, required_mongo_indexes


class DocumentRepositoryError(RuntimeError):
    """Expected canonical fact-store failure."""


class DocumentStore(Protocol):
    async def get_document(self, document_id: str) -> Document | None: ...

    async def list_documents(self, *, limit: int) -> list[Document]: ...

    async def get_canonical_evidence(
        self, candidates: list[RankedCandidate]
    ) -> list[Evidence]: ...

    async def get_evidence_for_rerank(
        self, candidates: list[RankedCandidate]
    ) -> list[Evidence]: ...

    async def create_document(self, document: Document) -> None: ...

    async def create_version(self, version: DocumentVersion) -> None: ...

    async def create_chunks(self, chunks: list[Chunk]) -> None: ...

    async def persist_ingested_version(
        self,
        document: Document,
        version: DocumentVersion,
        chunks: list[Chunk],
        *,
        create_document: bool,
    ) -> None: ...

    async def list_versions(self, document_id: str) -> list[DocumentVersion]: ...

    async def get_version(self, version_id: str) -> DocumentVersion | None: ...

    async def list_chunks_for_version(self, version_id: str) -> list[Chunk]: ...

    async def set_index_status(
        self, version_id: str, status: DocumentVersionStatus
    ) -> DocumentVersion: ...

    async def publish_version(self, version_id: str) -> DocumentVersion: ...

    async def archive_version(self, version_id: str) -> DocumentVersion: ...


def _to_bson(model: Document | DocumentVersion | Chunk) -> dict[str, Any]:
    document = model.model_dump(mode="python")
    document["_id"] = document.pop("id")
    return document


def _with_domain_id(document: dict[str, Any]) -> dict[str, Any]:
    value = dict(document)
    value["id"] = str(value.pop("_id"))
    return value


def canonical_evidence_pipeline(
    candidates: list[RankedCandidate], *, active_current_only: bool
) -> list[dict[str, Any]]:
    """Build the ordered fact-plane lookup used before and after reranking.

    The pre-rerank path reads title/text for indexed identities without making a
    lifecycle decision. The final path is stricter: the version must be factual
    and the document's current-active pointer must name that exact version.
    """

    identities = list(
        dict.fromkeys(
            (candidate.chunk_id, candidate.document_id, candidate.version_id)
            for candidate in candidates
        )
    )
    pipeline: list[dict[str, Any]] = [
        {
            "$match": {
                "$or": [
                    {
                        "_id": chunk_id,
                        "document_id": document_id,
                        "version_id": version_id,
                    }
                    for chunk_id, document_id, version_id in identities
                ]
            }
        },
        {
            "$lookup": {
                "from": "document_versions",
                "localField": "version_id",
                "foreignField": "_id",
                "as": "version",
            }
        },
        {"$unwind": "$version"},
        {
            "$lookup": {
                "from": "documents",
                "localField": "document_id",
                "foreignField": "_id",
                "as": "document",
            }
        },
        {"$unwind": "$document"},
    ]
    if active_current_only:
        pipeline.append(
            {
                "$match": {
                    "version.status": {
                        "$in": [
                            DocumentVersionStatus.ACTIVE.value,
                            DocumentVersionStatus.ACTIVE_WITH_WARNING.value,
                        ]
                    },
                    "$expr": {
                        "$eq": ["$document.current_active_version_id", "$version._id"]
                    },
                }
            }
        )
    pipeline.append(
        {
            "$project": {
                "_id": 1,
                "document_id": 1,
                "version_id": 1,
                "text": 1,
                "title": "$version.title",
                "status": "$version.status",
                "document_number": "$version.document_number",
                "written_date": "$version.written_date",
                "department": "$document.department_id",
                "source_url": "$document.source_url",
            }
        }
    )
    return pipeline


class MongoDocumentRepository:
    """Real MongoDB persistence for the canonical policy fact plane."""

    def __init__(self, settings: Settings) -> None:
        self._client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongo_uri)
        self._database: AsyncDatabase[dict[str, Any]] = self._client[settings.mongo_db]
        self._documents: AsyncCollection[dict[str, Any]] = self._database["documents"]
        self._versions: AsyncCollection[dict[str, Any]] = self._database["document_versions"]
        self._chunks: AsyncCollection[dict[str, Any]] = self._database["chunks"]

    async def close(self) -> None:
        await self._client.close()

    async def initialize_indexes(self) -> None:
        collections: dict[str, AsyncCollection[dict[str, Any]]] = {
            "documents": self._documents,
            "document_versions": self._versions,
            "chunks": self._chunks,
            "departments": self._database["departments"],
        }
        for collection_name, indexes in required_mongo_indexes().items():
            collection = collections[collection_name]
            for index in indexes:
                await self._create_index(collection, index)

    @staticmethod
    async def _create_index(collection: AsyncCollection[dict[str, Any]], index: MongoIndex) -> None:
        kwargs: dict[str, Any] = {"name": index.name, "unique": index.unique}
        if index.partial_filter is not None:
            kwargs["partialFilterExpression"] = dict(index.partial_filter)
        await collection.create_index(list(index.keys), **kwargs)

    async def create_document(self, document: Document) -> None:
        try:
            await self._documents.insert_one(_to_bson(document))
        except DuplicateKeyError as error:
            raise DocumentRepositoryError(f"Document already exists: {document.id}") from error

    async def create_version(self, version: DocumentVersion) -> None:
        try:
            await self._versions.insert_one(_to_bson(version))
        except DuplicateKeyError as error:
            raise DocumentRepositoryError(
                f"Duplicate document version or SHA-256: {version.document_id}/{version.version_no}"
            ) from error

    async def create_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        try:
            await self._chunks.insert_many([_to_bson(chunk) for chunk in chunks], ordered=True)
        except DuplicateKeyError as error:
            raise DocumentRepositoryError("Duplicate chunk version/ordinal.") from error

    async def persist_ingested_version(
        self,
        document: Document,
        version: DocumentVersion,
        chunks: list[Chunk],
        *,
        create_document: bool,
    ) -> None:
        """Atomically persist an upload's canonical document, parsed version, and chunks."""

        try:
            async with self._client.start_session() as session:
                async with await session.start_transaction():
                    if create_document:
                        await self._documents.insert_one(_to_bson(document), session=session)
                    await self._versions.insert_one(_to_bson(version), session=session)
                    if chunks:
                        await self._chunks.insert_many(
                            [_to_bson(chunk) for chunk in chunks],
                            ordered=True,
                            session=session,
                        )
        except DuplicateKeyError as error:
            raise DocumentRepositoryError(
                f"Duplicate document version or SHA-256: {version.document_id}/{version.version_no}"
            ) from error

    async def get_document(self, document_id: str) -> Document | None:
        document = await self._documents.find_one({"_id": document_id})
        return Document.model_validate(_with_domain_id(document)) if document else None

    async def list_documents(self, *, limit: int) -> list[Document]:
        cursor = self._documents.find({}).sort("updated_at", -1).limit(limit)
        return [Document.model_validate(_with_domain_id(document)) async for document in cursor]

    async def get_version(self, version_id: str) -> DocumentVersion | None:
        document = await self._versions.find_one({"_id": version_id})
        return DocumentVersion.model_validate(_with_domain_id(document)) if document else None

    async def list_chunks_for_version(self, version_id: str) -> list[Chunk]:
        cursor = self._chunks.find({"version_id": version_id}).sort("ordinal", 1)
        return [Chunk.model_validate(_with_domain_id(document)) async for document in cursor]

    async def set_index_status(
        self, version_id: str, status: DocumentVersionStatus
    ) -> DocumentVersion:
        """Persist the outcome of an external indexing attempt for one version."""

        now = datetime.now(UTC)
        changes: dict[str, Any] = {"status": status, "updated_at": now}
        if status is DocumentVersionStatus.READY:
            changes["indexed_at"] = now
        result = await self._versions.update_one({"_id": version_id}, {"$set": changes})
        if result.matched_count != 1:
            raise DocumentRepositoryError(f"Document version not found: {version_id}")
        version = await self.get_version(version_id)
        if version is None:  # Defensive: the row cannot vanish after a matched update.
            raise DocumentRepositoryError(f"Document version disappeared: {version_id}")
        return version

    async def list_versions(self, document_id: str) -> list[DocumentVersion]:
        cursor = self._versions.find({"document_id": document_id}).sort("version_no", 1)
        return [
            DocumentVersion.model_validate(_with_domain_id(document)) async for document in cursor
        ]

    async def get_active_version(self, document_id: str) -> DocumentVersion | None:
        document = await self._versions.find_one(
            {
                "document_id": document_id,
                "status": {
                    "$in": [DocumentVersionStatus.ACTIVE, DocumentVersionStatus.ACTIVE_WITH_WARNING]
                },
            }
        )
        return DocumentVersion.model_validate(_with_domain_id(document)) if document else None

    async def get_evidence_for_rerank(
        self, candidates: list[RankedCandidate]
    ) -> list[Evidence]:
        """Load candidate title/text for a cross-encoder without trusting lifecycle state."""

        return await self._get_candidate_evidence(candidates, active_current_only=False)

    async def get_canonical_evidence(
        self, candidates: list[RankedCandidate]
    ) -> list[Evidence]:
        """Final Mongo re-check for a factual current version after reranking."""

        return await self._get_candidate_evidence(candidates, active_current_only=True)

    async def _get_candidate_evidence(
        self, candidates: list[RankedCandidate], *, active_current_only: bool
    ) -> list[Evidence]:
        if not candidates:
            return []
        cursor = await self._chunks.aggregate(
            canonical_evidence_pipeline(candidates, active_current_only=active_current_only)
        )
        records = [record async for record in cursor]
        by_identity = {
            (str(record["_id"]), str(record["document_id"]), str(record["version_id"])): Evidence(
                chunk_id=str(record["_id"]),
                document_id=str(record["document_id"]),
                version_id=str(record["version_id"]),
                title=str(record["title"]),
                department=str(record["department"]),
                status=DocumentVersionStatus(str(record["status"])),
                text=str(record["text"]),
                document_number=(
                    str(record["document_number"])
                    if record.get("document_number") is not None
                    else None
                ),
                written_date=(
                    str(record["written_date"])
                    if record.get("written_date") is not None
                    else None
                ),
                source_url=(
                    str(record["source_url"]) if record.get("source_url") is not None else None
                ),
            )
            for record in records
        }
        return [
            by_identity[identity]
            for identity in (
                (candidate.chunk_id, candidate.document_id, candidate.version_id)
                for candidate in candidates
            )
            if identity in by_identity
        ]

    async def publish_version(self, version_id: str) -> DocumentVersion:
        """Publish a READY version and archive any previously active version in one transaction."""

        async with self._client.start_session() as session:
            async with await session.start_transaction():
                stored = await self._versions.find_one({"_id": version_id}, session=session)
                if stored is None:
                    raise DocumentRepositoryError(f"Document version not found: {version_id}")
                version = DocumentVersion.model_validate(_with_domain_id(stored))
                ensure_publishable(version.status)
                target_status = self._active_status(version.policy_status)
                now = datetime.now(UTC)
                update = await self._versions.update_one(
                    {"_id": version_id, "status": DocumentVersionStatus.READY},
                    {"$set": {"status": target_status, "updated_at": now}},
                    session=session,
                )
                if update.modified_count != 1:
                    raise DocumentRepositoryError(f"Version publish conflicted: {version_id}")
                await self._versions.update_many(
                    {
                        "document_id": version.document_id,
                        "_id": {"$ne": version_id},
                        "status": {
                            "$in": [
                                DocumentVersionStatus.ACTIVE,
                                DocumentVersionStatus.ACTIVE_WITH_WARNING,
                            ]
                        },
                    },
                    {"$set": {"status": DocumentVersionStatus.ARCHIVED, "updated_at": now}},
                    session=session,
                )
                document_update = await self._documents.update_one(
                    {"_id": version.document_id},
                    {"$set": {"current_active_version_id": version_id, "updated_at": now}},
                    session=session,
                )
                if document_update.modified_count != 1:
                    raise DocumentRepositoryError(
                        f"Parent document not found: {version.document_id}"
                    )
        published = await self.get_version(version_id)
        if published is None:
            raise DocumentRepositoryError(f"Published document version disappeared: {version_id}")
        return published

    async def archive_version(self, version_id: str) -> DocumentVersion:
        """Archive a version and clear its parent's active pointer when applicable."""

        async with self._client.start_session() as session:
            async with await session.start_transaction():
                stored = await self._versions.find_one({"_id": version_id}, session=session)
                if stored is None:
                    raise DocumentRepositoryError(f"Document version not found: {version_id}")
                version = DocumentVersion.model_validate(_with_domain_id(stored))
                now = datetime.now(UTC)
                result = await self._versions.update_one(
                    {"_id": version_id},
                    {"$set": {"status": DocumentVersionStatus.ARCHIVED, "updated_at": now}},
                    session=session,
                )
                unchanged = result.modified_count != 1
                if unchanged and version.status is not DocumentVersionStatus.ARCHIVED:
                    raise DocumentRepositoryError(f"Version archive conflicted: {version_id}")
                await self._documents.update_one(
                    {
                        "_id": version.document_id,
                        "current_active_version_id": version_id,
                    },
                    {"$set": {"current_active_version_id": None, "updated_at": now}},
                    session=session,
                )
        archived = await self.get_version(version_id)
        if archived is None:
            raise DocumentRepositoryError(f"Archived document version disappeared: {version_id}")
        return archived

    @staticmethod
    def _active_status(policy_status: PolicyStatus) -> DocumentVersionStatus:
        if policy_status is PolicyStatus.FULLY_EFFECTIVE:
            return DocumentVersionStatus.ACTIVE
        if policy_status is PolicyStatus.PARTIALLY_EFFECTIVE:
            return DocumentVersionStatus.ACTIVE_WITH_WARNING
        raise DocumentRepositoryError(
            f"Policy status {policy_status.value} cannot be published as factual evidence."
        )
