"""Real document-version indexing with cross-store consistency checks."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from backend.app.domain.documents import Chunk, Document, DocumentVersion, DocumentVersionStatus
from backend.app.retrieval.bm25 import BM25ChunkRecord, OpenSearchBM25
from backend.app.retrieval.dense import DenseVectorRecord, MilvusDenseIndex
from backend.app.retrieval.embedding import QueryEmbedder
from backend.app.storage.document_repository import DocumentStore


class IndexingError(RuntimeError):
    """A document version could not be safely prepared for publishing."""


class IndexableDocumentStore(DocumentStore, Protocol):
    async def get_version(self, version_id: str) -> DocumentVersion | None: ...

    async def list_chunks_for_version(self, version_id: str) -> list[Chunk]: ...

    async def set_index_status(
        self, version_id: str, status: DocumentVersionStatus
    ) -> DocumentVersion: ...


@dataclass(frozen=True, slots=True)
class IndexingResult:
    version: DocumentVersion
    mongo_chunk_count: int
    bm25_chunk_count: int
    dense_chunk_count: int


class DocumentIndexer:
    """Indexes one immutable version before it is eligible for publish.

    The external search planes are deliberately warmed before the Mongo publish
    transaction.  Canonical Mongo state is still authoritative, so the version
    cannot be cited until ``publish_version`` makes it ACTIVE.
    """

    def __init__(
        self,
        *,
        repository: IndexableDocumentStore,
        sparse: OpenSearchBM25,
        dense: MilvusDenseIndex,
        embedder: QueryEmbedder,
    ) -> None:
        self._repository = repository
        self._sparse = sparse
        self._dense = dense
        self._embedder = embedder

    async def index_version(self, version_id: str) -> DocumentVersion:
        """Write both retrieval indexes, smoke-check them, then mark READY."""

        version = await self._repository.get_version(version_id)
        if version is None:
            raise IndexingError(f"Document version not found: {version_id}")
        if version.status not in {DocumentVersionStatus.PARSED, DocumentVersionStatus.FAILED}:
            raise IndexingError(
                f"Only PARSED or FAILED versions may be indexed; got {version.status.value}."
            )
        document = await self._repository.get_document(version.document_id)
        if document is None:
            raise IndexingError(f"Parent document not found: {version.document_id}")
        chunks = await self._repository.list_chunks_for_version(version.id)
        if not chunks:
            raise IndexingError("Cannot index a version without canonical chunks.")

        await self._repository.set_index_status(version.id, DocumentVersionStatus.INDEXING)
        try:
            await self._sparse.initialize()
            await self._dense.initialize()
            embeddings = await self._embed_chunks(chunks)
            await self._sparse.index_records(
                self._bm25_records(document=document, version=version, chunks=chunks)
            )
            await self._dense.upsert(
                self._dense_records(
                    document=document, version=version, chunks=chunks, embeddings=embeddings
                )
            )
            result = await self._verify_consistency(
                document=document,
                version=version,
                chunks=chunks,
                probe_vector=embeddings[0],
            )
        except Exception as error:
            await self._repository.set_index_status(version.id, DocumentVersionStatus.FAILED)
            if isinstance(error, IndexingError):
                raise
            raise IndexingError(f"Indexing failed for {version.id}: {error}") from error

        ready = await self._repository.set_index_status(version.id, DocumentVersionStatus.READY)
        if result.mongo_chunk_count != len(chunks):  # Kept explicit for type-safe future changes.
            raise IndexingError("Canonical chunk count changed during indexing.")
        return ready

    async def _embed_chunks(self, chunks: Sequence[Chunk]) -> list[list[float]]:
        return [await self._embedder.embed(chunk.text) for chunk in chunks]

    @staticmethod
    def _bm25_records(
        *, document: Document, version: DocumentVersion, chunks: Sequence[Chunk]
    ) -> list[BM25ChunkRecord]:
        # These records are warmed under searchable lifecycle flags.  Mongo's
        # final active/current-pointer re-check is the gate that makes the
        # version visible as factual evidence after publication.
        return [
            BM25ChunkRecord(
                chunk_id=chunk.id,
                document_id=document.id,
                version_id=version.id,
                department_id=document.department_id,
                title=version.title,
                text=chunk.text,
            )
            for chunk in chunks
        ]

    @staticmethod
    def _dense_records(
        *,
        document: Document,
        version: DocumentVersion,
        chunks: Sequence[Chunk],
        embeddings: Sequence[list[float]],
    ) -> list[DenseVectorRecord]:
        return [
            DenseVectorRecord(
                chunk_id=chunk.id,
                document_id=document.id,
                version_id=version.id,
                department_id=document.department_id,
                embedding=embedding,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]

    async def _verify_consistency(
        self,
        *,
        document: Document,
        version: DocumentVersion,
        chunks: Sequence[Chunk],
        probe_vector: list[float],
    ) -> IndexingResult:
        expected = len(chunks)
        bm25_count = await self._sparse.count_version_records(version.id)
        dense_count = await self._dense.count_version_records(version.id)
        if bm25_count != expected or dense_count != expected:
            raise IndexingError(
                "Index consistency check failed: "
                f"mongo={expected}, bm25={bm25_count}, dense={dense_count}."
            )
        sparse_hits = await self._sparse.search(
            chunks[0].text, department_ids=[document.department_id], limit=1
        )
        dense_hits = await self._dense.search(
            probe_vector, department_ids=[document.department_id], limit=1
        )
        if not sparse_hits or not dense_hits:
            raise IndexingError("Index retrieval smoke test returned no result.")
        return IndexingResult(
            version=version,
            mongo_chunk_count=expected,
            bm25_chunk_count=bm25_count,
            dense_chunk_count=dense_count,
        )
