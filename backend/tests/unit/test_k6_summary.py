import importlib
import json
from pathlib import Path

import pytest


def _point(metric: str, value: float, timestamp: str) -> str:
    return json.dumps(
        {
            "metric": metric,
            "type": "Point",
            "data": {"time": timestamp, "value": value, "tags": {}},
        }
    )


def test_summarize_k6_run_recomputes_percentiles_and_failure_rate(tmp_path: Path) -> None:
    try:
        module = importlib.import_module("scripts.summarize_k6")
    except ModuleNotFoundError:
        pytest.fail("scripts.summarize_k6 must provide summarize_k6_run")

    raw_path = tmp_path / "raw.json"
    raw_path.write_text(
        "\n".join(
            [
                _point("http_req_duration", 100, "2026-10-09T00:00:00Z"),
                _point("http_req_duration", 200, "2026-10-09T00:00:01Z"),
                _point("http_req_duration", 300, "2026-10-09T00:00:02Z"),
                _point("http_req_duration", 400, "2026-10-09T00:00:03Z"),
                _point("http_req_duration", 500, "2026-10-09T00:00:04Z"),
                _point("http_req_failed", 0, "2026-10-09T00:00:00Z"),
                _point("http_req_failed", 1, "2026-10-09T00:00:01Z"),
                _point("http_reqs", 1, "2026-10-09T00:00:00Z"),
                _point("http_reqs", 1, "2026-10-09T00:00:04Z"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = module.summarize_k6_run(
        raw_path,
        vus=10,
        requested_duration="5m",
    )

    assert summary["total_requests"] == 2
    assert summary["throughput_rps"] == pytest.approx(0.5)
    assert summary["p50_latency_ms"] == pytest.approx(300)
    assert summary["p95_latency_ms"] == pytest.approx(480)
    assert summary["p99_latency_ms"] == pytest.approx(496)
    assert summary["error_rate"] == pytest.approx(0.5)
    assert summary["checks_passed"] is False
