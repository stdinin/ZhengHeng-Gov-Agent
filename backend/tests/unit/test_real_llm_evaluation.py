import importlib

import pytest

from backend.app.llm.base import LLMTokenUsage


def test_real_llm_metrics_aggregate_usage_cost_citations_and_abstention() -> None:
    try:
        module = importlib.import_module("backend.app.evaluation.real_llm")
    except ModuleNotFoundError:
        pytest.fail("real_llm evaluation helpers must be available")

    ledger = module.UsageLedger()
    ledger.record(
        LLMTokenUsage(
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            cached_input_tokens=25,
            uncached_input_tokens=75,
        )
    )
    pricing = module.DeepSeekPricing(
        cached_input_usd_per_million=0.003,
        uncached_input_usd_per_million=0.15,
        output_usd_per_million=0.6,
        period="off_peak",
    )
    assert ledger.cost_usd(pricing) == pytest.approx(0.000023325)

    results = [
        module.GenerationCaseResult(
            case_id="factual",
            factual=True,
            expected_abstain=False,
            status="SUCCESS",
            cited_chunk_ids=["chunk_gold"],
            gold_chunk_ids=["chunk_gold"],
            routed_department_ids=["dept_tax"],
            gold_department_ids=["dept_tax"],
            latency_ms=100.0,
        ),
        module.GenerationCaseResult(
            case_id="gap",
            factual=False,
            expected_abstain=True,
            status="ABSTAIN",
            cited_chunk_ids=[],
            gold_chunk_ids=[],
            routed_department_ids=["other"],
            gold_department_ids=[],
            latency_ms=200.0,
        ),
    ]

    metrics = module.compute_generation_metrics(results)

    assert metrics["citation_coverage"] == pytest.approx(1.0)
    assert metrics["citation_correctness"] == pytest.approx(1.0)
    assert metrics["abstain_knowledge_gap_accuracy"] == pytest.approx(1.0)
    assert metrics["routing_accuracy"] == pytest.approx(1.0)
    assert metrics["p50_latency_ms"] == pytest.approx(150.0)
