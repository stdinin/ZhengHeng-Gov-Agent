"""Run a small, explicitly opt-in DeepSeek generation E2E validation profile.

This profile never reads a credential from source control or writes it to its
artifacts.  It is deliberately separate from the FakeLLM observability and k6
profiles, so an unavailable external provider is not a P0 acceptance blocker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import Settings
from backend.app.evaluation.real_llm import (
    DeepSeekPricing,
    GenerationCaseResult,
    UsageLedger,
    compute_generation_metrics,
    serialize_pricing,
)
from backend.app.evaluation.schemas import EvalCase, EvalCaseType
from backend.app.harness.composition import build_chat_service
from backend.app.llm.base import LLMTokenUsage
from backend.app.llm.openai_compatible import OpenAICompatibleLLM
from backend.app.storage.document_repository import MongoDocumentRepository
from backend.app.storage.trace_repository import MongoTraceStore

_PRICING = {
    "peak": DeepSeekPricing(
        cached_input_usd_per_million=0.006,
        uncached_input_usd_per_million=0.3,
        output_usd_per_million=1.2,
        period="peak",
    ),
    "off_peak": DeepSeekPricing(
        cached_input_usd_per_million=0.003,
        uncached_input_usd_per_million=0.15,
        output_usd_per_million=0.6,
        period="off_peak",
    ),
}


def require_deepseek_api_key(environment: Mapping[str, str]) -> str:
    """Get the key from the process environment without printing or persisting it."""

    key = environment.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is required for the opt-in real-provider profile. "
            "Do not put it in source control or artifacts."
        )
    return key


def _load_cases(path: Path) -> list[EvalCase]:
    cases = [
        EvalCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases or not all(case.frozen for case in cases):
        raise ValueError("A non-empty frozen eval set is required.")
    return cases


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evalset", default="evalsets/policy_eval_v1.jsonl")
    parser.add_argument("--output", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--pricing-period", choices=tuple(_PRICING), required=True)
    parser.add_argument("--phase", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--smoke-cases", type=int, default=5)
    parser.add_argument("--mongo-db", default="zhengheng_public_eval_v1")
    parser.add_argument("--opensearch-index", default="policy_chunks_public_eval_v1")
    parser.add_argument("--milvus-collection", default="policy_chunks_public_eval_v1")
    return parser.parse_args()


def _select_cases(args: argparse.Namespace, cases: list[EvalCase]) -> list[EvalCase]:
    if args.phase == "full":
        return cases
    if args.smoke_cases <= 0:
        raise ValueError("--smoke-cases must be positive.")
    return cases[: args.smoke_cases]


def _usage_payload(entries: list[LLMTokenUsage], pricing: DeepSeekPricing) -> dict[str, object]:
    ledger = UsageLedger()
    for item in entries:
        ledger.record(item)
    return {
        "provider_call_count": ledger.call_count,
        "tokens": ledger.snapshot(),
        "estimated_cost_usd": ledger.cost_usd(pricing),
    }


async def _run(args: argparse.Namespace) -> Path:
    # The secret is held in memory only and never added to config/artifacts/errors.
    api_key = require_deepseek_api_key(os.environ)
    pricing = _PRICING[args.pricing_period]
    evalset = Path(args.evalset)
    cases = _select_cases(args, _load_cases(evalset))
    run_id = args.run_id or (
        f"real_llm_deepseek_flash_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    run_dir = Path(args.output) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    config = {
        "profile": "Real-LLM E2E Validation (DeepSeek deepseek-flash)",
        "provider": "OpenAI-compatible DeepSeek API",
        "model": "deepseek-flash",
        "phase": args.phase,
        "case_count": len(cases),
        "evalset_sha256": sha256(evalset.read_bytes()).hexdigest(),
        "pricing": serialize_pricing(pricing),
        "pricing_source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "credential_source": "process environment variable DEEPSEEK_API_KEY only",
        "credential_persisted": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "evalset.jsonl").write_bytes(evalset.read_bytes())

    settings = Settings(
        mongo_db=args.mongo_db,
        opensearch_index=args.opensearch_index,
        milvus_collection=args.milvus_collection,
        llm_mode="remote",
        llm_base_url="https://api.deepseek.com",
        llm_api_key=api_key,
        llm_model="deepseek-flash",
    )
    usage_entries: list[LLMTokenUsage] = []
    repository = MongoDocumentRepository(settings)
    traces = MongoTraceStore(settings)
    provider = OpenAICompatibleLLM(settings, usage_sink=usage_entries.append)
    service = build_chat_service(
        settings,
        document_store=repository,
        trace_store=traces,
        llm_client=provider,
    )
    rows: list[dict[str, object]] = []
    metric_rows: list[GenerationCaseResult] = []
    try:
        for index, case in enumerate(cases, start=1):
            before_usage = len(usage_entries)
            trace_id = f"real-llm-{run_id}-{index}-{uuid4()}"
            started = time.perf_counter()
            result = await service.answer(
                query=case.question,
                trace_id=trace_id,
                session_id=f"real-llm-{run_id}",
                user_id="eval-real-llm",
            )
            latency_ms = round((time.perf_counter() - started) * 1_000, 2)
            case_usage = usage_entries[before_usage:]
            if not case_usage:
                raise RuntimeError(
                    "Provider returned no token usage for a real E2E case; "
                    "the run cannot be reported as provider-validated."
                )
            citations = [citation.chunk_id for citation in result.citations]
            routed = (
                [route.department_id for route in result.state.department_routes.routes]
                if result.state.department_routes is not None
                else []
            )
            factual = case.case_type is not EvalCaseType.KNOWLEDGE_GAP
            metric_rows.append(
                GenerationCaseResult(
                    case_id=case.id,
                    factual=factual,
                    expected_abstain=case.case_type is EvalCaseType.KNOWLEDGE_GAP,
                    status=result.status.value,
                    cited_chunk_ids=citations,
                    gold_chunk_ids=case.gold_chunk_ids,
                    routed_department_ids=routed,
                    gold_department_ids=case.gold_department_ids,
                    latency_ms=latency_ms,
                )
            )
            rows.append(
                {
                    "case_id": case.id,
                    "case_type": case.case_type.value,
                    "status": result.status.value,
                    "citation_chunk_ids": citations,
                    "gold_chunk_ids": case.gold_chunk_ids,
                    "routed_department_ids": routed,
                    "gold_department_ids": case.gold_department_ids,
                    "latency_ms": latency_ms,
                    "trace_id": trace_id,
                    "usage": _usage_payload(case_usage, pricing),
                }
            )
            print(f"real-llm: complete {index}/{len(cases)} {case.id}", flush=True)
    finally:
        await service.close()
        await repository.close()
        await traces.close()

    metrics: dict[str, object] = dict(compute_generation_metrics(metric_rows))
    metrics.update(
        {
            "case_count": len(metric_rows),
            "provider_usage": _usage_payload(usage_entries, pricing),
            "metric_notes": {
                "answer_correctness": "NOT_AVAILABLE_FROM_DATASET: frozen eval has no answer gold.",
                "citation_correctness": (
                    "A cited chunk is correct only when it belongs to the frozen gold chunk IDs."
                ),
                "abstain_knowledge_gap_accuracy": "Only evaluated on frozen KNOWLEDGE_GAP cases.",
            },
        }
    )
    (run_dir / "raw_predictions.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"real-llm: artifact {run_dir}", flush=True)
    return run_dir


def main() -> None:
    args = _parse_args()
    run_dir = asyncio.run(_run(args))
    print(run_dir, flush=True)


if __name__ == "__main__":
    main()
