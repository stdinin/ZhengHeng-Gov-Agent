"""Validate V1.1 multi-agent metrics, Prometheus scrape, and PII redaction."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

PII_VALUES = ("13800138000", "user@example.com", "11010519491231002X")
QUERY = "税务登记条件；联系方式13800138000，邮箱user@example.com。"
FORBIDDEN_LABELS = ("query=", "user_id=", "trace_id=", "name=", "phone=")
REQUIRED_METRICS = (
    "zhengheng_runtime_invocations_total",
    "zhengheng_runtime_latency_seconds",
    "zhengheng_orchestrator_requests_total",
    "zhengheng_orchestrator_fanout_size",
    "zhengheng_department_agent_calls_total",
    "zhengheng_department_agent_latency_seconds",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9092")
    parser.add_argument("--email", default="user@example.local")
    parser.add_argument("--password", default="demo-user")
    parser.add_argument("--output", type=Path, default=Path("runs/v11_observability"))
    return parser.parse_args()


def prometheus_scalar(client: httpx.Client, base_url: str, query: str) -> float:
    response = client.get(f"{base_url.rstrip('/')}/api/v1/query", params={"query": query})
    response.raise_for_status()
    result = response.json()["data"]["result"]
    return float(result[0]["value"][1]) if result else 0.0


def validate(args: argparse.Namespace) -> Path:
    args.output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=45) as client:
        before = client.get(f"{args.api_url.rstrip('/')}/metrics")
        before.raise_for_status()
        login = client.post(
            f"{args.api_url.rstrip('/')}/api/v1/auth/login",
            json={"email": args.email, "password": args.password},
        )
        login.raise_for_status()
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
            "X-Trace-Id": f"v11-observability-{uuid4()}",
        }
        response = client.post(
            f"{args.api_url.rstrip('/')}/api/v1/chat",
            headers=headers,
            json={"query": QUERY, "session_id": headers["X-Trace-Id"]},
        )
        response.raise_for_status()
        chat = response.json()
        if chat["status"] != "SUCCESS" or chat.get("orchestration", {}).get("fanout") != 1:
            raise RuntimeError(
                "V1.1 observability request did not produce one verified department call"
            )
        trace = client.get(
            f"{args.api_url.rstrip('/')}/api/v1/traces/{chat['trace_id']}",
            headers=headers,
        )
        trace.raise_for_status()
        after = client.get(f"{args.api_url.rstrip('/')}/metrics")
        after.raise_for_status()

        metrics_text = after.text
        missing = [name for name in REQUIRED_METRICS if name not in metrics_text]
        if missing:
            raise RuntimeError(f"Missing V1.1 metric families: {missing}")
        labels = re.findall(r"\{([^}]*)\}", metrics_text)
        metric_leaks = [value for value in PII_VALUES if value in metrics_text]
        trace_json = json.dumps(trace.json(), ensure_ascii=False)
        trace_leaks = [value for value in PII_VALUES if value in trace_json]
        forbidden = [label for label in labels if any(item in label for item in FORBIDDEN_LABELS)]
        if metric_leaks or trace_leaks or forbidden:
            raise RuntimeError(
                f"PII or high-cardinality labels detected: metrics={metric_leaks}, "
                f"trace={trace_leaks}, labels={forbidden}"
            )

        scrape_query = "zhengheng_orchestrator_requests_total"
        deadline = time.monotonic() + 45
        up = 0.0
        scraped = 0.0
        while time.monotonic() < deadline:
            up = prometheus_scalar(
                client,
                args.prometheus_url,
                'up{job="zhengheng-v11-orchestrator"}',
            )
            scraped = prometheus_scalar(client, args.prometheus_url, scrape_query)
            if up == 1.0 and scraped >= 1.0:
                break
            time.sleep(3)
        if up != 1.0 or scraped < 1.0:
            raise RuntimeError(f"Prometheus scrape unavailable: up={up}, requests={scraped}")

    artifact: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "profile": "V1.1 Compose multi-agent with Pi Faux",
        "api_url": args.api_url,
        "prometheus_url": args.prometheus_url,
        "chat_status": chat["status"],
        "orchestration": chat["orchestration"],
        "metric_families": REQUIRED_METRICS,
        "prometheus": {"up": up, "orchestrator_requests_total": scraped},
        "pii_redaction": {
            "trace_passed": not trace_leaks,
            "metrics_passed": not metric_leaks,
            "forbidden_labels": forbidden,
        },
    }
    output = args.output / "v11_observability_validation.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    print(validate(parse_args()))
