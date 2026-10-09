"""Metrics and accounting helpers for small-sample real-provider E2E validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from statistics import median

from backend.app.llm.base import LLMTokenUsage


@dataclass(frozen=True, slots=True)
class DeepSeekPricing:
    """Explicit per-million-token prices selected for one recorded billing period."""

    cached_input_usd_per_million: float
    uncached_input_usd_per_million: float
    output_usd_per_million: float
    period: str


@dataclass(frozen=True, slots=True)
class GenerationCaseResult:
    case_id: str
    factual: bool
    expected_abstain: bool
    status: str
    cited_chunk_ids: list[str]
    gold_chunk_ids: list[str]
    routed_department_ids: list[str]
    gold_department_ids: list[str]
    latency_ms: float


class UsageLedger:
    """Accumulates provider response usage only; prompts and credentials are never retained."""

    def __init__(self) -> None:
        self._entries: list[LLMTokenUsage] = []

    def record(self, usage: LLMTokenUsage) -> None:
        self._entries.append(usage)

    @property
    def call_count(self) -> int:
        return len(self._entries)

    def snapshot(self) -> dict[str, int | None]:
        input_tokens = self._sum("input_tokens")
        output_tokens = self._sum("output_tokens")
        total_tokens = self._sum("total_tokens")
        cached_input_tokens = self._sum("cached_input_tokens", allow_missing=True)
        uncached_input_tokens = self._sum("uncached_input_tokens", allow_missing=True)
        if input_tokens is not None and uncached_input_tokens is None:
            uncached_input_tokens = max(input_tokens - (cached_input_tokens or 0), 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cached_input_tokens": cached_input_tokens,
            "uncached_input_tokens": uncached_input_tokens,
        }

    def cost_usd(self, pricing: DeepSeekPricing) -> float | None:
        usage = self.snapshot()
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        uncached_input_tokens = usage["uncached_input_tokens"]
        if input_tokens is None or output_tokens is None or uncached_input_tokens is None:
            return None
        cached_input_tokens = usage["cached_input_tokens"] or 0
        return (
            cached_input_tokens * pricing.cached_input_usd_per_million
            + uncached_input_tokens * pricing.uncached_input_usd_per_million
            + output_tokens * pricing.output_usd_per_million
        ) / 1_000_000

    def _sum(self, field: str, *, allow_missing: bool = False) -> int | None:
        values = [getattr(entry, field) for entry in self._entries]
        if not values:
            return 0
        if any(value is None for value in values):
            return 0 if allow_missing else None
        return sum(int(value) for value in values if value is not None)


def compute_generation_metrics(results: list[GenerationCaseResult]) -> dict[str, float | str]:
    if not results:
        raise ValueError("Generation evaluation requires at least one result.")
    factual = [result for result in results if result.factual]
    gaps = [result for result in results if result.expected_abstain]
    routing_cases = [result for result in results if result.gold_department_ids]
    latencies = sorted(result.latency_ms for result in results)
    return {
        "generation_success_rate": _mean(
            float(result.status == "SUCCESS") for result in factual
        )
        if factual
        else "NOT_AVAILABLE_FROM_DATASET",
        "citation_coverage": _mean(float(bool(result.cited_chunk_ids)) for result in factual)
        if factual
        else "NOT_AVAILABLE_FROM_DATASET",
        "citation_correctness": _mean(
            float(
                bool(result.cited_chunk_ids)
                and set(result.cited_chunk_ids).issubset(set(result.gold_chunk_ids))
            )
            for result in factual
        )
        if factual
        else "NOT_AVAILABLE_FROM_DATASET",
        "abstain_knowledge_gap_accuracy": _mean(
            float(result.status == "ABSTAIN") for result in gaps
        )
        if gaps
        else "NOT_AVAILABLE_FROM_DATASET",
        "routing_accuracy": _mean(
            float(bool(set(result.routed_department_ids) & set(result.gold_department_ids)))
            for result in routing_cases
        )
        if routing_cases
        else "NOT_AVAILABLE_FROM_DATASET",
        "answer_correctness": "NOT_AVAILABLE_FROM_DATASET",
        "p50_latency_ms": median(latencies),
        "p95_latency_ms": _percentile(latencies, 0.95),
    }


def serialize_pricing(pricing: DeepSeekPricing) -> dict[str, float | str]:
    return asdict(pricing)


def _mean(values: Iterable[float]) -> float:
    normalized = list(values)
    return sum(normalized) / len(normalized)


def _percentile(values: list[float], percentile: float) -> float:
    position = (len(values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction
