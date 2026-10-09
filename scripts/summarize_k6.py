"""Create a reproducible performance summary from k6 raw JSON output."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a percentile without values.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_k6_run(
    raw_path: Path,
    *,
    vus: int,
    requested_duration: str,
) -> dict[str, Any]:
    """Recompute request metrics from raw k6 points without hard-coded results."""

    durations_ms: list[float] = []
    failure_values: list[float] = []
    check_values: list[float] = []
    request_times: list[datetime] = []
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if payload.get("type") != "Point":
            continue
        metric = payload.get("metric")
        data = payload["data"]
        if metric == "http_req_duration":
            durations_ms.append(float(data["value"]))
        elif metric == "http_req_failed":
            failure_values.append(float(data["value"]))
        elif metric == "checks":
            check_values.append(float(data["value"]))
        elif metric == "http_reqs":
            request_times.append(datetime.fromisoformat(data["time"].replace("Z", "+00:00")))

    if not durations_ms or not request_times:
        raise ValueError("Raw k6 output does not contain HTTP request points.")
    observed_seconds = (max(request_times) - min(request_times)).total_seconds()
    if observed_seconds <= 0:
        raise ValueError("Raw k6 output has no positive request observation interval.")
    error_rate = sum(failure_values) / len(failure_values) if failure_values else 0.0
    checks_passed = error_rate == 0.0 and all(value == 1.0 for value in check_values)

    return {
        "profile": "Harness / Retrieval Infrastructure Performance (FakeLLM)",
        "raw_artifact": str(raw_path),
        "vus": vus,
        "requested_duration": requested_duration,
        "observed_duration_seconds": observed_seconds,
        "total_requests": len(request_times),
        "throughput_rps": len(request_times) / observed_seconds,
        "p50_latency_ms": _percentile(durations_ms, 0.50),
        "p95_latency_ms": _percentile(durations_ms, 0.95),
        "p99_latency_ms": _percentile(durations_ms, 0.99),
        "error_rate": error_rate,
        "checks_passed": checks_passed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--vus", type=int, required=True)
    parser.add_argument("--duration", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = summarize_k6_run(args.raw, vus=args.vus, requested_duration=args.duration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
