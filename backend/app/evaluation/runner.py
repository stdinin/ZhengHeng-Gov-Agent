import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

from backend.app.evaluation.metrics import mean_reciprocal_rank, recall_at_k


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    case_id: str
    ranked_chunk_ids: list[str]
    gold_chunk_ids: list[str]
    latency_ms: float
    success: bool
    abstained: bool


@dataclass(frozen=True, slots=True)
class EvalMetrics:
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    recall_at_10: float
    mrr: float
    answer_success_rate: float
    abstention_accuracy: float
    p50_latency_ms: float
    p95_latency_ms: float


def compute_metrics(results: list[EvalCaseResult]) -> EvalMetrics:
    if not results:
        raise ValueError("An evaluation run needs at least one case result.")
    ranked = [result.ranked_chunk_ids for result in results]
    gold = [set(result.gold_chunk_ids) for result in results]
    latencies = sorted(result.latency_ms for result in results)
    recalls = {
        k: _mean(
            [
                recall_at_k(items, expected, k)
                for items, expected in zip(ranked, gold, strict=True)
            ]
        )
        for k in (1, 3, 5, 10)
    }
    return EvalMetrics(
        recall_at_1=recalls[1],
        recall_at_3=recalls[3],
        recall_at_5=recalls[5],
        recall_at_10=recalls[10],
        mrr=mean_reciprocal_rank(ranked, gold),
        answer_success_rate=_mean([float(result.success) for result in results]),
        abstention_accuracy=_mean([float(result.abstained) for result in results]),
        p50_latency_ms=median(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
    )


def write_report(*, run_id: str, metrics: EvalMetrics, output_root: Path) -> Path:
    run_directory = output_root / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    (run_directory / "metrics.json").write_text(
        json.dumps(asdict(metrics), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_directory / "report.md").write_text(
        "# Evaluation Report\n\n"
        f"- Run ID: `{run_id}`\n"
        f"- Recall@5: {metrics.recall_at_5:.4f}\n"
        f"- MRR: {metrics.mrr:.4f}\n"
        f"- Answer success rate: {metrics.answer_success_rate:.4f}\n",
        encoding="utf-8",
    )
    return run_directory


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    index = min(len(sorted_values) - 1, int((len(sorted_values) - 1) * fraction))
    return sorted_values[index]
