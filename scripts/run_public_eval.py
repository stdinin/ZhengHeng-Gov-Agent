"""Run process-isolated public-corpus retrieval evaluation and ablations."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if TYPE_CHECKING:
    from backend.app.evaluation.schemas import EvalCase
    from backend.app.retrieval.rrf import RankedCandidate

PROFILES = (
    "bm25",
    "dense",
    "bm25_dense_rrf",
    "bm25_dense_rrf_reranker",
    "full_canonical_active_recheck",
)


def _load_evaluate_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported public-eval checkpoint: {path}")
    return cast(dict[str, Any], payload)


def _save_evaluate_checkpoint(
    path: Path,
    *,
    predictions: dict[str, dict[str, list[str]]],
    latencies: dict[str, list[float]],
    raw_predictions: list[dict[str, object]],
    retrieval_rows: list[dict[str, object]],
    trace_rows: list[dict[str, object]],
    complete: bool = False,
) -> None:
    payload = {
        "schema_version": 1,
        "complete": complete,
        "completed_case_ids": [str(row["case_id"]) for row in raw_predictions],
        "predictions": predictions,
        "latencies": latencies,
        "raw_predictions": raw_predictions,
        "retrieval_rows": retrieval_rows,
        "trace_rows": trace_rows,
    }
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_cases(path: Path) -> list[EvalCase]:
    from backend.app.evaluation.schemas import EvalCase

    cases = [
        EvalCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases or not all(case.frozen for case in cases):
        raise ValueError("A non-empty frozen eval set is required.")
    return cases


async def _embed(args: argparse.Namespace) -> None:
    from backend.app.config import Settings
    from backend.app.retrieval.embedding import build_embedding_provider

    cases = _load_cases(Path(args.evalset))
    embedder = build_embedding_provider(Settings())
    payload: dict[str, list[float]] = {}
    for case in cases:
        payload[case.id] = await embedder.embed(case.question)
    Path(args.embeddings).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _ranked_from_fused(fused: list[Any]) -> list[RankedCandidate]:
    from backend.app.retrieval.rrf import RankedCandidate

    return [
        RankedCandidate(
            chunk_id=item.chunk_id,
            document_id=item.document_id,
            version_id=item.version_id,
            rank=rank,
            raw_score=item.rrf_score,
        )
        for rank, item in enumerate(fused, start=1)
    ]


def _profile_metrics(
    cases: list[EvalCase], predictions: dict[str, list[str]], latencies: list[float]
) -> dict[str, float]:
    from backend.app.evaluation.metrics import mean_reciprocal_rank, recall_at_k

    factual = [case for case in cases if case.gold_chunk_ids]
    ranked = [predictions[case.id] for case in factual]
    gold = [set(case.gold_chunk_ids) for case in factual]
    ordered_latencies = sorted(latencies)
    return {
        "recall_at_1": sum(
            recall_at_k(items, expected, 1)
            for items, expected in zip(ranked, gold, strict=True)
        )
        / len(factual),
        "recall_at_5": sum(
            recall_at_k(items, expected, 5)
            for items, expected in zip(ranked, gold, strict=True)
        )
        / len(factual),
        "recall_at_10": sum(
            recall_at_k(items, expected, 10)
            for items, expected in zip(ranked, gold, strict=True)
        )
        / len(factual),
        "mrr": mean_reciprocal_rank(ranked, gold),
        "p50_latency_ms": median(ordered_latencies),
        "p95_latency_ms": ordered_latencies[
            min(len(ordered_latencies) - 1, int(len(ordered_latencies) * 0.95))
        ],
    }


async def _evaluate(args: argparse.Namespace) -> None:
    from backend.app.config import Settings
    from backend.app.evaluation.schemas import EvalCaseType
    from backend.app.retrieval.bm25 import OpenSearchBM25
    from backend.app.retrieval.dense import MilvusDenseIndex
    from backend.app.retrieval.reranker import CrossEncoderReranker, ScoredEvidence
    from backend.app.retrieval.rrf import RankedCandidate, reciprocal_rank_fusion
    from backend.app.storage.document_repository import MongoDocumentRepository

    run_dir = Path(args.run_dir)
    checkpoint_path = run_dir / "evaluate_checkpoint.json"
    cases = _load_cases(Path(args.evalset))
    embeddings = json.loads(Path(args.embeddings).read_text(encoding="utf-8"))
    settings = Settings(mongo_db=args.mongo_db)
    repository = MongoDocumentRepository(settings)
    sparse = OpenSearchBM25(settings, index_name=args.opensearch_index)
    dense = MilvusDenseIndex(
        settings,
        collection_name=args.milvus_collection,
        embedding_dim=settings.embedding_dimension,
        embedding_model=settings.embedding_model,
    )
    reranker = CrossEncoderReranker(model_name=settings.reranker_model)
    print("evaluate: repositories configured; CrossEncoder will load lazily", flush=True)
    checkpoint = _load_evaluate_checkpoint(checkpoint_path)
    if checkpoint is None:
        predictions: dict[str, dict[str, list[str]]] = {
            profile: {} for profile in PROFILES
        }
        latencies: dict[str, list[float]] = {profile: [] for profile in PROFILES}
        raw_predictions: list[dict[str, object]] = []
        retrieval_rows: list[dict[str, object]] = []
        trace_rows: list[dict[str, object]] = []
        completed_case_ids: set[str] = set()
    else:
        predictions = checkpoint["predictions"]
        latencies = checkpoint["latencies"]
        raw_predictions = checkpoint["raw_predictions"]
        retrieval_rows = checkpoint["retrieval_rows"]
        trace_rows = checkpoint["trace_rows"]
        completed_case_ids = {
            str(case_id) for case_id in checkpoint["completed_case_ids"]
        }
        print(
            f"evaluate: resume {len(completed_case_ids)}/{len(cases)} completed cases",
            flush=True,
        )
    try:
        await sparse.initialize()
        await dense.initialize()
        evaluated_this_process = 0
        for case in cases:
            if case.id in completed_case_ids:
                continue
            print(f"evaluate: start {case.id}", flush=True)
            vector = [float(value) for value in embeddings[case.id]]
            started = time.perf_counter()
            bm25 = await sparse.search(case.question, department_ids=("dept_tax",), limit=40)
            bm25_ms = (time.perf_counter() - started) * 1_000
            started = time.perf_counter()
            dense_hits = await dense.search(vector, department_ids=["dept_tax"], limit=40)
            dense_ms = (time.perf_counter() - started) * 1_000
            started = time.perf_counter()
            fused = reciprocal_rank_fusion({"bm25": bm25, "dense": dense_hits}, rrf_k=60)[:60]
            fused_candidates = _ranked_from_fused(fused)
            rrf_ms = (time.perf_counter() - started) * 1_000
            rerank_evidence = await repository.get_evidence_for_rerank(fused_candidates)
            fused_scores = {
                (item.chunk_id, item.document_id, item.version_id): item.rrf_score
                for item in fused
            }
            scored = [
                ScoredEvidence(
                    evidence=item,
                    rrf_score=fused_scores[(item.chunk_id, item.document_id, item.version_id)],
                )
                for item in rerank_evidence
                if (item.chunk_id, item.document_id, item.version_id) in fused_scores
            ][: settings.rerank_top_n]
            started = time.perf_counter()
            reranked = await reranker.rerank(
                case.question, scored, limit=settings.rerank_top_n
            )
            rerank_ms = (time.perf_counter() - started) * 1_000
            reranked_candidates = [
                RankedCandidate(
                    chunk_id=item.evidence.chunk_id,
                    document_id=item.evidence.document_id,
                    version_id=item.evidence.version_id,
                    rank=rank,
                )
                for rank, item in enumerate(reranked, start=1)
            ]
            started = time.perf_counter()
            canonical = await repository.get_canonical_evidence(reranked_candidates)
            canonical_ms = (time.perf_counter() - started) * 1_000
            per_profile = {
                "bm25": [item.chunk_id for item in bm25],
                "dense": [item.chunk_id for item in dense_hits],
                "bm25_dense_rrf": [item.chunk_id for item in fused],
                "bm25_dense_rrf_reranker": [item.evidence.chunk_id for item in reranked],
                "full_canonical_active_recheck": [item.chunk_id for item in canonical],
            }
            per_latency = {
                "bm25": bm25_ms,
                "dense": dense_ms,
                "bm25_dense_rrf": bm25_ms + dense_ms + rrf_ms,
                "bm25_dense_rrf_reranker": bm25_ms + dense_ms + rrf_ms + rerank_ms,
                "full_canonical_active_recheck": (
                    bm25_ms + dense_ms + rrf_ms + rerank_ms + canonical_ms
                ),
            }
            for profile in PROFILES:
                predictions[profile][case.id] = per_profile[profile]
                latencies[profile].append(per_latency[profile])
            cited = per_profile["full_canonical_active_recheck"][:8]
            raw_predictions.append(
                {
                    "case_id": case.id,
                    "case_type": case.case_type.value,
                    "status": "SUCCESS" if cited else "ABSTAIN",
                    "citation_chunk_ids": cited,
                    "gold_chunk_ids": case.gold_chunk_ids,
                }
            )
            retrieval_rows.append({"case_id": case.id, "profiles": per_profile})
            trace_rows.append(
                {
                    "case_id": case.id,
                    "stage_counts": {
                        "bm25": len(bm25),
                        "dense": len(dense_hits),
                        "fused": len(fused),
                        "reranked": len(reranked),
                        "canonical": len(canonical),
                    },
                    "latency_ms": per_latency,
                }
            )
            print(f"evaluate: complete {case.id}", flush=True)
            _save_evaluate_checkpoint(
                checkpoint_path,
                predictions=predictions,
                latencies=latencies,
                raw_predictions=raw_predictions,
                retrieval_rows=retrieval_rows,
                trace_rows=trace_rows,
            )
            evaluated_this_process += 1
            if (
                args.max_evaluate_cases > 0
                and evaluated_this_process >= args.max_evaluate_cases
                and len(raw_predictions) < len(cases)
            ):
                print(
                    "evaluate: process case limit reached; checkpoint saved",
                    flush=True,
                )
                return
    finally:
        await sparse.close()
        await repository.close()

    ablations = {
        profile: _profile_metrics(cases, predictions[profile], latencies[profile])
        for profile in PROFILES
    }
    factual_rows = [row for row in raw_predictions if row["gold_chunk_ids"]]
    gap_rows = [
        row
        for row in raw_predictions
        if row["case_type"] == EvalCaseType.KNOWLEDGE_GAP.value
    ]
    citation_total = sum(len(_row_ids(row, "citation_chunk_ids")) for row in factual_rows)
    citation_correct = sum(
        len(set(_row_ids(row, "citation_chunk_ids")) & set(_row_ids(row, "gold_chunk_ids")))
        for row in factual_rows
    )
    citation_covered = sum(
        int(
            bool(
                set(_row_ids(row, "citation_chunk_ids"))
                & set(_row_ids(row, "gold_chunk_ids"))
            )
        )
        for row in factual_rows
    )
    metrics: dict[str, object] = dict(ablations["full_canonical_active_recheck"])
    metrics.update(
        {
            "citation_correctness": citation_correct / citation_total if citation_total else 0.0,
            "citation_coverage": citation_covered / len(factual_rows),
            "abstain_knowledge_gap_accuracy": sum(
                row["status"] == "ABSTAIN" for row in gap_rows
            )
            / len(gap_rows),
            "answer_correctness": "NOT_AVAILABLE_FROM_DATASET",
            "routing_accuracy": "NOT_AVAILABLE_FROM_DATASET",
            "factual_case_count": len(factual_rows),
            "knowledge_gap_case_count": len(gap_rows),
        }
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "ablation_results.json").write_text(
        json.dumps(ablations, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_jsonl(run_dir / "raw_predictions.jsonl", raw_predictions)
    _write_jsonl(run_dir / "retrieval_results.jsonl", retrieval_rows)
    _write_jsonl(run_dir / "traces.jsonl", trace_rows)
    lines = [
        "# Retrieval Ablation",
        "",
        "| Profile | Recall@1 | Recall@5 | Recall@10 | MRR | P95 ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for profile in PROFILES:
        item = ablations[profile]
        lines.append(
            f"| {profile} | {item['recall_at_1']:.4f} | {item['recall_at_5']:.4f} | "
            f"{item['recall_at_10']:.4f} | {item['mrr']:.4f} | "
            f"{item['p95_latency_ms']:.2f} |"
        )
    (run_dir / "ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _save_evaluate_checkpoint(
        checkpoint_path,
        predictions=predictions,
        latencies=latencies,
        raw_predictions=raw_predictions,
        retrieval_rows=retrieval_rows,
        trace_rows=trace_rows,
        complete=True,
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _row_ids(row: dict[str, object], key: str) -> list[str]:
    value = row[key]
    if not isinstance(value, list):
        raise TypeError(f"Evaluation row field {key!r} must be a list.")
    return [str(item) for item in value]


def _completed_case_count(checkpoint_path: Path) -> int:
    checkpoint = _load_evaluate_checkpoint(checkpoint_path)
    if checkpoint is None:
        return 0
    return len(checkpoint["completed_case_ids"])


def _windows_available_commit_bytes() -> int | None:
    if sys.platform != "win32":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    kernel32 = cast(Any, ctypes).windll.kernel32
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullAvailPageFile)


def _wait_for_windows_commit(*, minimum_bytes: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        available = _windows_available_commit_bytes()
        if available is None or available >= minimum_bytes:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Windows commit space did not recover to the model-load threshold: "
                f"available={available}, required={minimum_bytes}."
            )
        print(
            "evaluate supervisor: waiting for Windows commit release "
            f"({available / 1024**3:.2f} GiB available)",
            flush=True,
        )
        time.sleep(10)


def _resume_evaluate(args: argparse.Namespace) -> None:
    """Run real evaluation in restartable subprocesses for Windows native isolation."""

    run_dir = Path(args.run_dir)
    checkpoint_path = run_dir / "evaluate_checkpoint.json"
    history_path = run_dir / "evaluate_process_history.json"
    total_cases = len(_load_cases(Path(args.evalset)))
    history: list[dict[str, object]] = []
    if history_path.is_file():
        loaded_history = json.loads(history_path.read_text(encoding="utf-8"))
        if isinstance(loaded_history, list):
            history = cast(list[dict[str, object]], loaded_history)
    environment = dict(os.environ)
    environment["HF_HUB_OFFLINE"] = "1"
    environment["HF_DATASETS_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["OMP_NUM_THREADS"] = "8"
    environment["MKL_NUM_THREADS"] = "8"
    command = [
        sys.executable,
        "-X",
        "faulthandler",
        "-u",
        str(Path(__file__).resolve()),
        "--stage",
        "evaluate",
        "--evalset",
        str(Path(args.evalset).resolve()),
        "--manifest",
        str(Path(args.manifest).resolve()),
        "--run-dir",
        str(run_dir.resolve()),
        "--embeddings",
        str(Path(args.embeddings).resolve()),
        "--mongo-db",
        args.mongo_db,
        "--opensearch-index",
        args.opensearch_index,
        "--milvus-collection",
        args.milvus_collection,
        "--max-evaluate-cases",
        "1",
    ]
    for attempt in range(total_cases + 1):
        before = _completed_case_count(checkpoint_path)
        if before == total_cases:
            checkpoint = _load_evaluate_checkpoint(checkpoint_path)
            if checkpoint is not None and checkpoint.get("complete") is True:
                return
        print(
            f"evaluate supervisor: attempt {attempt + 1}, progress {before}/{total_cases}",
            flush=True,
        )
        _wait_for_windows_commit(
            minimum_bytes=int(5.8 * 1024**3), timeout_seconds=180
        )
        started = time.perf_counter()
        completed = subprocess.run(command, env=environment, check=False)
        duration_seconds = time.perf_counter() - started
        after = _completed_case_count(checkpoint_path)
        history.append(
            {
                "attempt": attempt + 1,
                "return_code": completed.returncode,
                "completed_before": before,
                "completed_after": after,
                "duration_seconds": duration_seconds,
            }
        )
        history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if completed.returncode == 0 and after == total_cases:
            checkpoint = _load_evaluate_checkpoint(checkpoint_path)
            if (
                checkpoint is not None
                and checkpoint.get("complete") is True
            ):
                return
            raise RuntimeError(
                "Public eval subprocess returned 0 without a complete checkpoint."
            )
        if after <= before:
            raise RuntimeError(
                "Public eval subprocess failed without checkpoint progress: "
                f"return_code={completed.returncode}, completed={after}/{total_cases}."
            )
        exit_kind = "clean case boundary" if completed.returncode == 0 else "native exit"
        print(
            f"evaluate supervisor: {exit_kind} recorded; resuming from "
            f"{after}/{total_cases}",
            flush=True,
        )
    raise RuntimeError("Public eval exceeded the bounded subprocess restart count.")


def _orchestrate(args: argparse.Namespace) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or f"public_eval_{timestamp}_{uuid4().hex[:8]}"
    run_dir = Path(args.output) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    evalset = Path(args.evalset)
    manifest = Path(args.manifest)
    embeddings = run_dir / "query_embeddings.json"
    config = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "evalset": str(evalset),
        "evalset_sha256": sha256(evalset.read_bytes()).hexdigest(),
        "dataset_manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
        "profiles": list(PROFILES),
        "llm": "none; retrieval/citation evaluation only",
        "process_isolation": ["bge-m3 query embedding", "cross-encoder retrieval eval"],
    }
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "dataset_manifest.json").write_bytes(manifest.read_bytes())
    (run_dir / "evalset.jsonl").write_bytes(evalset.read_bytes())
    common = [
        sys.executable,
        "-X",
        "faulthandler",
        "-u",
        str(Path(__file__).resolve()),
        "--evalset",
        str(evalset.resolve()),
        "--manifest",
        str(manifest.resolve()),
        "--run-dir",
        str(run_dir.resolve()),
        "--embeddings",
        str(embeddings.resolve()),
        "--mongo-db",
        args.mongo_db,
        "--opensearch-index",
        args.opensearch_index,
        "--milvus-collection",
        args.milvus_collection,
    ]
    environment = dict(os.environ)
    environment["HF_HUB_OFFLINE"] = "1"
    environment["HF_DATASETS_OFFLINE"] = "1"
    completed = subprocess.run(
        [*common, "--stage", "embed"],
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Public eval stage 'embed' failed with {completed.returncode}.")
    args.run_dir = str(run_dir.resolve())
    args.embeddings = str(embeddings.resolve())
    _resume_evaluate(args)
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("all", "embed", "evaluate", "resume-evaluate"),
        default="all",
    )
    parser.add_argument("--evalset", default="evaluation/evalsets/policy_eval_v1.jsonl")
    parser.add_argument("--manifest", default="evaluation/manifests/chinatax_policy_v1.json")
    parser.add_argument("--output", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--embeddings", default="")
    parser.add_argument("--mongo-db", default="zhengheng_public_eval_v1")
    parser.add_argument("--opensearch-index", default="policy_chunks_public_eval_v1")
    parser.add_argument("--milvus-collection", default="policy_chunks_public_eval_v1")
    parser.add_argument("--max-evaluate-cases", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    if parsed.stage == "embed":
        asyncio.run(_embed(parsed))
    elif parsed.stage == "evaluate":
        asyncio.run(_evaluate(parsed))
    elif parsed.stage == "resume-evaluate":
        _resume_evaluate(parsed)
    else:
        print(_orchestrate(parsed))
