"""Seed three small canonical documents through the real V1.0 ingestion path.

This is a deterministic V1.1 acceptance fixture, not a production corpus and
not an in-memory retrieval substitute. Each document is indexed in Mongo,
OpenSearch and Milvus before being atomically published ACTIVE.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import Settings
from backend.app.domain.documents import (
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    PolicyStatus,
    SourceType,
)
from backend.app.ingestion.indexer import DocumentIndexer
from backend.app.retrieval.bm25 import OpenSearchBM25
from backend.app.retrieval.dense import MilvusDenseIndex
from backend.app.retrieval.embedding import build_embedding_provider
from backend.app.storage.document_repository import MongoDocumentRepository

_RECORDS = (
    ("tax", "V1.1 税务政策示例", "税务登记和增值税申报应依照现行税收政策办理。"),
    ("hrss", "V1.1 人社政策示例", "社会保险参保和就业服务应依照现行人社政策办理。"),
    ("housing", "V1.1 住房政策示例", "住房公积金和保障性住房申请应依照现行住房政策办理。"),
)


async def main() -> None:
    settings = Settings()
    repository = MongoDocumentRepository(settings)
    sparse = OpenSearchBM25(settings, index_name=settings.opensearch_index)
    dense = MilvusDenseIndex(settings, collection_name=settings.milvus_collection)
    indexer = DocumentIndexer(
        repository=repository,
        sparse=sparse,
        dense=dense,
        embedder=build_embedding_provider(settings),
    )
    indexed = 0
    try:
        await repository.initialize_indexes()
        await sparse.initialize()
        await dense.initialize()
        for department_id, title, text in _RECORDS:
            document_id = f"v11_demo_{department_id}"
            version_id = f"v11_demo_{department_id}_v1"
            existing = await repository.get_version(version_id)
            if existing is None:
                now = datetime.now(UTC)
                digest = sha256(text.encode("utf-8")).hexdigest()
                document = Document(
                    id=document_id,
                    logical_name=title,
                    department_id=department_id,
                    source_type=SourceType.DATASET,
                    source_dataset="zhengheng-v11-multi-agent-fixture",
                    current_active_version_id=None,
                    created_at=now,
                    updated_at=now,
                )
                version = DocumentVersion(
                    id=version_id,
                    document_id=document_id,
                    version_no=1,
                    sha256=digest,
                    status=DocumentVersionStatus.PARSED,
                    policy_status=PolicyStatus.FULLY_EFFECTIVE,
                    title=title,
                    raw_text=text,
                    chunk_count=1,
                    trace_id=f"seed_v11_{department_id}",
                    created_at=now,
                    updated_at=now,
                )
                chunk = Chunk(
                    id=f"v11_demo_{department_id}_chunk_1",
                    document_id=document_id,
                    version_id=version_id,
                    ordinal=1,
                    text=text,
                    trace_id=version.trace_id,
                    created_at=now,
                    updated_at=now,
                )
                await repository.persist_ingested_version(
                    document, version, [chunk], create_document=True
                )
                existing = version
            if existing.status is DocumentVersionStatus.INDEXING:
                # The native Windows process can terminate during first model
                # construction. Keep canonical data and explicitly make the
                # interrupted, unpublished version retryable.
                existing = await repository.set_index_status(
                    version_id, DocumentVersionStatus.FAILED
                )
            if existing.status in {DocumentVersionStatus.PARSED, DocumentVersionStatus.FAILED}:
                await indexer.index_version(version_id)
                existing = await repository.get_version(version_id)
            if existing is not None and existing.status is DocumentVersionStatus.READY:
                await repository.publish_version(version_id)
                indexed += 1
            elif existing is not None and existing.status is DocumentVersionStatus.ACTIVE:
                indexed += 1
            else:
                raise RuntimeError(f"Unexpected V1.1 demo document status for {version_id}")
        print(f"V1.1 multi-agent demo seed ready: {indexed} ACTIVE documents")
    finally:
        await sparse.close()
        await repository.close()


if __name__ == "__main__":
    asyncio.run(main())
