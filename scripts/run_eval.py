"""Run a frozen evaluation set against a real authenticated chat deployment.

This script intentionally stops on unavailable infrastructure. It never substitutes a fake
provider or synthetic metrics for a real policy retrieval evaluation.
"""

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.evaluation.runner import EvalCaseResult, compute_metrics, write_report
from backend.app.evaluation.schemas import EvalCase


async def run(args: argparse.Namespace) -> Path:
    token = os.environ.get("ZH_EVAL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "ZH_EVAL_ACCESS_TOKEN is required and must be supplied through the environment."
        )
    cases = _load_cases(Path(args.evalset))
    headers = {"Authorization": f"Bearer {token}"}
    results: list[EvalCaseResult] = []
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), timeout=args.timeout
    ) as client:
        for case in cases:
            started = datetime.now(UTC)
            response = await client.post("/chat", headers=headers, json={"query": case.question})
            elapsed_ms = (datetime.now(UTC) - started).total_seconds() * 1_000
            if response.status_code != 200:
                raise RuntimeError(
                    f"Chat evaluation stopped for {case.id}: HTTP {response.status_code}. "
                    "Do not treat this as an evaluation result."
                )
            payload = response.json()
            citations = payload.get("citations")
            if not isinstance(citations, list):
                raise RuntimeError(f"Chat response for {case.id} omitted a citations list.")
            results.append(
                EvalCaseResult(
                    case_id=case.id,
                    ranked_chunk_ids=[str(item["chunk_id"]) for item in citations],
                    gold_chunk_ids=case.gold_chunk_ids,
                    latency_ms=elapsed_ms,
                    success=payload.get("status") == "SUCCESS",
                    abstained=payload.get("status") == "ABSTAIN",
                )
            )
    metrics = compute_metrics(results)
    return write_report(
        run_id=args.run_id or str(uuid4()),
        metrics=metrics,
        output_root=Path(args.output),
    )


def _load_cases(path: Path) -> list[EvalCase]:
    cases = [
        EvalCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases:
        raise ValueError("Evaluation set contains no cases.")
    if not all(case.frozen for case in cases):
        raise ValueError("Only frozen eval cases may be used for an evaluation run.")
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a frozen eval set against the real chat API.")
    parser.add_argument("--evalset", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--output", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--timeout", type=float, default=90)
    return parser.parse_args()


if __name__ == "__main__":
    print(asyncio.run(run(parse_args())))
