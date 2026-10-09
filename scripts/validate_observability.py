"""Validate real API metrics, Prometheus scraping, and persisted trace PII redaction."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PII_VALUES = (
    "13800138000",
    "user@example.com",
    "11010519491231002X",
)
QUERY = (
    "我的手机号是13800138000，邮箱user@example.com，身份证11010519491231002X，"
    "请说明增值税政策办理条件。"
)


def _metric_value(payload: str, name: str) -> float:
    for line in payload.splitlines():
        if line.startswith(f"{name} "):
            return float(line.rsplit(" ", maxsplit=1)[1])
    return 0.0


def _prometheus_scalar(client: httpx.Client, prometheus_url: str, query: str) -> float:
    response = client.get(
        f"{prometheus_url}/api/v1/query",
        params={"query": query},
    )
    response.raise_for_status()
    result = response.json()["data"]["result"]
    if not result:
        return 0.0
    return float(result[0]["value"][1])


def run(args: argparse.Namespace) -> Path:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(300.0)) as client:
        before_payload = client.get(f"{args.api_url}/metrics").text
        login = client.post(
            f"{args.api_url}/api/v1/auth/login",
            json={"email": args.email, "password": args.password},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        chat = client.post(
            f"{args.api_url}/api/v1/chat",
            json={"query": QUERY, "session_id": "observability-pii-validation"},
            headers=headers,
        )
        chat.raise_for_status()
        chat_payload = chat.json()
        trace = client.get(
            f"{args.api_url}/api/v1/traces/{chat_payload['trace_id']}",
            headers=headers,
        )
        trace.raise_for_status()
        trace_payload = trace.json()
        after_payload = client.get(f"{args.api_url}/metrics").text

        request_before = _metric_value(before_payload, "zh_chat_requests_total")
        request_after = _metric_value(after_payload, "zh_chat_requests_total")
        if request_after != request_before + 1:
            raise RuntimeError(
                "Chat request counter did not increase exactly once: "
                f"before={request_before}, after={request_after}."
            )
        required_metrics = (
            "zh_chat_requests_total",
            "zh_chat_errors_total",
            "zh_abstain_total",
            "zh_verifier_fail_total",
            "zh_chat_latency_seconds_count",
            'zh_node_latency_seconds_count{node="Retrieve"}',
            'zh_node_latency_seconds_count{node="Verify"}',
        )
        missing = [name for name in required_metrics if name not in after_payload]
        if missing:
            raise RuntimeError(f"Required metrics are missing: {missing}")

        trace_json = json.dumps(trace_payload, ensure_ascii=False)
        leaked_trace_values = [value for value in PII_VALUES if value in trace_json]
        leaked_metric_values = [value for value in PII_VALUES if value in after_payload]
        labels = re.findall(r"\{([^}]+)\}", after_payload)
        if leaked_trace_values or leaked_metric_values:
            raise RuntimeError(
                "PII validation failed: "
                f"trace={leaked_trace_values}, metrics={leaked_metric_values}."
            )
        if any(
            not re.fullmatch(
                r'node="(Intent|Rewrite|Route|Retrieve|Answer|Verify)"', label
            )
            for label in labels
        ):
            raise RuntimeError(f"Unexpected Prometheus label set: {labels}")

        deadline = time.monotonic() + 60
        prometheus_up = 0.0
        scraped_requests = 0.0
        while time.monotonic() < deadline:
            prometheus_up = _prometheus_scalar(
                client,
                args.prometheus_url,
                'up{job="zhengheng-api"}',
            )
            scraped_requests = _prometheus_scalar(
                client,
                args.prometheus_url,
                "zh_chat_requests_total",
            )
            if prometheus_up == 1.0 and scraped_requests >= request_after:
                break
            time.sleep(5)
        if prometheus_up != 1.0 or scraped_requests < request_after:
            raise RuntimeError(
                "Prometheus did not scrape the observed request metrics: "
                f"up={prometheus_up}, scraped={scraped_requests}, expected={request_after}."
            )

    artifact: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "api_url": args.api_url,
        "prometheus_url": args.prometheus_url,
        "llm_mode": "fake",
        "chat_status": chat_payload["status"],
        "trace_id": chat_payload["trace_id"],
        "metrics": {
            "chat_requests_before": request_before,
            "chat_requests_after": request_after,
            "chat_requests_delta": request_after - request_before,
            "chat_errors_total": _metric_value(after_payload, "zh_chat_errors_total"),
            "abstain_total": _metric_value(after_payload, "zh_abstain_total"),
            "verifier_fail_total": _metric_value(after_payload, "zh_verifier_fail_total"),
        },
        "prometheus": {
            "up": prometheus_up,
            "scraped_chat_requests_total": scraped_requests,
        },
        "pii_redaction": {
            "trace_passed": not leaked_trace_values,
            "metrics_passed": not leaked_metric_values,
            "allowed_labels": labels,
        },
    }
    output_path = output_dir / "observability_validation.json"
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    parser.add_argument("--email", default="user@example.local")
    parser.add_argument("--password", default="demo-user")
    parser.add_argument("--output", default="runs/observability_v1")
    return parser.parse_args()


if __name__ == "__main__":
    print(run(parse_args()))
