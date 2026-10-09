"""Deterministically ingest the public China tax corpus through all fact planes."""

import argparse
import asyncio
import json
import random
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from datasets import load_dataset  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import Settings
from backend.app.domain.documents import (
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionStatus,
    SourceType,
)
from backend.app.evaluation.schemas import EvalCase, EvalCaseType
from backend.app.ingestion.adapters.chinatax import (
    CHINATAX_DATASET_ID,
    normalize_chinatax_record,
)
from backend.app.ingestion.chunker import chunk_text
from backend.app.ingestion.indexer import DocumentIndexer
from backend.app.retrieval.bm25 import OpenSearchBM25
from backend.app.retrieval.dense import MilvusDenseIndex
from backend.app.retrieval.embedding import build_embedding_provider
from backend.app.storage.document_repository import MongoDocumentRepository

DATASET_REVISION = "db52ff69471dab17eef664fa7814d62798745720"
QUESTION_TEMPLATE = "请依据《{title}》说明该政策的主要规定。"


def _stable_rows(rows: list[dict[str, Any]], *, seed: int) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: sha256(
            f"{row.get('title', '')}\n{row.get('content', '')}".encode()
        ).hexdigest(),
    )
    random.Random(seed).shuffle(ordered)
    return ordered


def _ids(content_hash: str) -> tuple[str, str]:
    key = content_hash[:24]
    return f"doc_ct_{key}", f"ver_ct_{key}_v1"


async def run(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings(mongo_db=args.mongo_db, reranker_enabled=False)
    repository = MongoDocumentRepository(settings)
    sparse = OpenSearchBM25(settings, index_name=args.opensearch_index)
    dense = MilvusDenseIndex(
        settings,
        collection_name=args.milvus_collection,
        embedding_dim=settings.embedding_dimension,
        embedding_model=settings.embedding_model,
    )
    indexer = DocumentIndexer(
        repository=repository,
        sparse=sparse,
        dense=dense,
        embedder=build_embedding_provider(settings),
    )
    dataset = load_dataset(CHINATAX_DATASET_ID, revision=DATASET_REVISION, split="train")
    source_rows = [dict(row) for row in dataset]
    normalized = [normalize_chinatax_record(row) for row in source_rows]
    active_rows = [
        row
        for row, policy in zip(source_rows, normalized, strict=True)
        if policy.status is DocumentVersionStatus.ACTIVE
        and len(policy.content) <= args.max_content_chars
    ]
    gap_rows = [
        row
        for row, policy in zip(source_rows, normalized, strict=True)
        if policy.status is DocumentVersionStatus.ARCHIVED
    ]
    selected = _stable_rows(active_rows, seed=args.seed)[: args.limit]
    selected_gaps = _stable_rows(gap_rows, seed=args.seed + 1)[: args.gap_size]
    if len(selected) < args.limit:
        raise RuntimeError(
            f"Only {len(selected)} eligible ACTIVE rows satisfy the deterministic size cap."
        )

    manifest_rows: list[dict[str, object]] = []
    eval_cases: list[EvalCase] = []
    imported_documents = 0
    imported_chunks = 0
    selected_chunks = 0
    now = datetime.now(UTC)
    try:
        await repository.initialize_indexes()
        await sparse.initialize()
        await dense.initialize()
        for ordinal, raw_row in enumerate(selected, start=1):
            if args.max_new_documents and imported_documents >= args.max_new_documents:
                break
            policy = normalize_chinatax_record(raw_row)
            document_id, version_id = _ids(policy.sha256)
            drafts = chunk_text(
                document_id=document_id,
                version_id=version_id,
                text=policy.content,
                max_chars=args.chunk_chars,
            )
            trace_id = f"bootstrap_{policy.sha256[:24]}"
            document = Document(
                id=document_id,
                logical_name=policy.title,
                department_id="dept_tax",
                source_type=SourceType.DATASET,
                source_dataset=policy.source_dataset,
                source_url=policy.source_url,
                created_at=now,
                updated_at=now,
            )
            version = DocumentVersion(
                id=version_id,
                document_id=document_id,
                version_no=1,
                sha256=policy.sha256,
                status=DocumentVersionStatus.PARSED,
                policy_status=policy.policy_status,
                title=policy.title,
                document_number=policy.document_number,
                issuing_department_raw=policy.issuing_department,
                written_date=policy.written_date,
                channel=policy.channel,
                effect_level=policy.effect_level,
                raw_text=policy.content,
                parse_metadata={
                    "source_dataset": policy.source_dataset,
                    "dataset_revision": DATASET_REVISION,
                    "source_aging": str(raw_row.get("aging", "")),
                },
                chunk_count=len(drafts),
                trace_id=trace_id,
                created_at=now,
                updated_at=now,
            )
            chunks = [
                Chunk(
                    id=draft.id,
                    document_id=draft.document_id,
                    version_id=draft.version_id,
                    ordinal=draft.ordinal,
                    text=draft.text,
                    heading_path=draft.heading_path,
                    char_start=draft.char_start,
                    char_end=draft.char_end,
                    token_count_estimate=max(1, len(draft.text) // 2),
                    created_at=now,
                    updated_at=now,
                    trace_id=trace_id,
                )
                for draft in drafts
            ]
            stored = await repository.get_document(document_id)
            if stored is None:
                await repository.persist_ingested_version(
                    document,
                    version,
                    chunks,
                    create_document=True,
                )
                await indexer.index_version(version_id)
                await repository.publish_version(version_id)
                imported_documents += 1
                imported_chunks += len(chunks)
            else:
                stored_version = await repository.get_version(version_id)
                if stored_version is None:
                    raise RuntimeError(
                        f"Document {document_id} exists without deterministic version {version_id}."
                    )
                if stored_version.status is DocumentVersionStatus.INDEXING:
                    stored_version = await repository.set_index_status(
                        version_id, DocumentVersionStatus.FAILED
                    )
                if stored_version.status in {
                    DocumentVersionStatus.PARSED,
                    DocumentVersionStatus.FAILED,
                }:
                    stored_version = await indexer.index_version(version_id)
                if stored_version.status is DocumentVersionStatus.READY:
                    await repository.publish_version(version_id)
                elif stored_version.status not in {
                    DocumentVersionStatus.ACTIVE,
                    DocumentVersionStatus.ACTIVE_WITH_WARNING,
                }:
                    raise RuntimeError(
                        f"Cannot resume {version_id} from {stored_version.status.value}."
                    )
            manifest_rows.append(
                {
                    "ordinal": ordinal,
                    "document_id": document_id,
                    "version_id": version_id,
                    "sha256": policy.sha256,
                    "source_url": policy.source_url,
                    "title": policy.title,
                    "chunk_ids": [chunk.id for chunk in chunks],
                }
            )
            selected_chunks += len(chunks)
            if len(eval_cases) < args.eval_size:
                eval_cases.append(
                    EvalCase(
                        id=f"eval_ct_{policy.sha256[:20]}",
                        question=QUESTION_TEMPLATE.format(title=policy.title),
                        gold_department_ids=["dept_tax"],
                        gold_doc_ids=[document_id],
                        gold_version_ids=[version_id],
                        gold_chunk_ids=[chunks[0].id],
                        gold_answer_points=[],
                        case_type=EvalCaseType.SINGLE_DEPT,
                        frozen=True,
                        metadata={
                            "source_dataset": policy.source_dataset,
                            "source_sha256": policy.sha256,
                            "question_generator": "deterministic-title-template-v1",
                        },
                    )
                )
    finally:
        await sparse.close()
        await repository.close()

    for raw_row in selected_gaps:
        policy = normalize_chinatax_record(raw_row)
        eval_cases.append(
            EvalCase(
                id=f"eval_gap_{policy.sha256[:20]}",
                question=QUESTION_TEMPLATE.format(title=policy.title),
                gold_department_ids=["dept_tax"],
                gold_doc_ids=[],
                gold_version_ids=[],
                gold_chunk_ids=[],
                gold_answer_points=[],
                case_type=EvalCaseType.KNOWLEDGE_GAP,
                frozen=True,
                metadata={
                    "source_dataset": policy.source_dataset,
                    "source_sha256": policy.sha256,
                    "source_aging": str(raw_row.get("aging", "")),
                    "reason": "public source is archived and intentionally excluded from facts",
                },
            )
        )

    manifest_path = Path(args.manifest)
    evalset_path = Path(args.evalset)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    evalset_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset_id": CHINATAX_DATASET_ID,
        "dataset_revision": DATASET_REVISION,
        "license": "cc-by-nc-4.0",
        "seed": args.seed,
        "selection": {
            "required_aging": "全文有效",
            "max_content_chars": args.max_content_chars,
            "limit": args.limit,
        },
        "mongo_db": args.mongo_db,
        "opensearch_index": args.opensearch_index,
        "milvus_collection": args.milvus_collection,
        "embedding_model": settings.embedding_model,
        "documents": manifest_rows,
        "document_count": len(manifest_rows),
        "chunk_count": selected_chunks,
        "newly_imported_document_count": imported_documents,
        "newly_imported_chunk_count": imported_chunks,
        "eval_case_count": len(eval_cases),
        "question_template_sha256": sha256(QUESTION_TEMPLATE.encode()).hexdigest(),
        "manual_review": "NOT_COMPLETED",
        "created_at": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evalset_path.write_text(
        "\n".join(case.model_dump_json() for case in eval_cases) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--eval-size", type=int, default=20)
    parser.add_argument("--gap-size", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--max-content-chars", type=int, default=6_000)
    parser.add_argument("--chunk-chars", type=int, default=1_000)
    parser.add_argument(
        "--max-new-documents",
        type=int,
        default=0,
        help="Bound new embeddings per process; zero processes the full deterministic selection.",
    )
    parser.add_argument("--mongo-db", default="zhengheng_public_eval_v1")
    parser.add_argument("--opensearch-index", default="policy_chunks_public_eval_v1")
    parser.add_argument("--milvus-collection", default="policy_chunks_public_eval_v1")
    parser.add_argument("--manifest", default="data/manifests/chinatax_policy_v1.json")
    parser.add_argument("--evalset", default="evalsets/policy_eval_v1.jsonl")
    return parser.parse_args()


if __name__ == "__main__":
    result = asyncio.run(run(parse_args()))
    print(json.dumps({key: value for key, value in result.items() if key != "documents"}, indent=2))
