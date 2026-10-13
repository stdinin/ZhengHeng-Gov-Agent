"""Run the frozen V1.1 engineering fixture against real Compose services.

The runner never replaces MongoDB, OpenSearch, Milvus, Redis, Pi Runtime or a
department HTTP service with a fake.  The two fault cases deliberately pause
or stop one real Compose department container, then restore it in ``finally``.
The resulting artifacts are explicitly an ``INTEGRATION_FIXTURE`` evaluation,
not a public-policy benchmark or a real external-LLM quality claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "eval" / "multi_agent_eval.jsonl"

FaultMode = Literal["pause", "stop"]


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    kind: Literal["single", "cross", "fault"]
    query: str
    expected_departments: frozenset[str]
    expected_outcome: Literal["success", "partial"]
    fault_mode: FaultMode | None = None
    fault_department: str | None = None
    expected_failure_reason: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("V11_MULTI_AGENT_BASE_URL"))
    parser.add_argument("--email", default=os.getenv("V11_MULTI_AGENT_EMAIL", "user@example.local"))
    parser.add_argument(
        "--password", default=os.getenv("V11_MULTI_AGENT_PASSWORD", "demo-user")
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    parser.add_argument("--compose-project-dir", type=Path, default=ROOT)
    return parser.parse_args()


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        item = cast(dict[str, Any], json.loads(raw_line))
        try:
            kind = cast(Literal["single", "cross", "fault"], item["kind"])
            outcome = cast(Literal["success", "partial"], item["expected_outcome"])
            fault_mode = item.get("fault_mode")
            if fault_mode is not None and fault_mode not in {"pause", "stop"}:
                raise ValueError("fault_mode must be pause or stop")
            case = EvalCase(
                case_id=str(item["id"]),
                kind=kind,
                query=str(item["query"]),
                expected_departments=frozenset(
                    str(value) for value in item["expected_departments"]
                ),
                expected_outcome=outcome,
                fault_mode=cast(FaultMode | None, fault_mode),
                fault_department=(
                    str(item["fault_department"]) if item.get("fault_department") else None
                ),
                expected_failure_reason=(
                    str(item["expected_failure_reason"])
                    if item.get("expected_failure_reason")
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid fixture line {number}: {error}") from error
        if case.kind == "fault" and (case.fault_mode is None or case.fault_department is None):
            raise ValueError(
                f"Fault case {case.case_id} must declare fault_mode and fault_department"
            )
        cases.append(case)
    if len(cases) != 12:
        raise ValueError(f"Expected exactly 12 frozen V1.1 fixture cases, got {len(cases)}")
    if sum(case.kind == "single" for case in cases) != 4:
        raise ValueError("Fixture must contain four single-department cases")
    if sum(case.kind == "cross" for case in cases) != 6:
        raise ValueError("Fixture must contain six cross-department cases")
    if sum(case.kind == "fault" for case in cases) != 2:
        raise ValueError("Fixture must contain two real fault cases")
    return cases


def compose(*arguments: str, cwd: Path) -> None:
    subprocess.run(["docker", "compose", *arguments], cwd=cwd, check=True)


def authenticate(client: httpx.Client, *, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def inject_fault(case: EvalCase, *, project_dir: Path) -> None:
    assert case.fault_mode is not None and case.fault_department is not None
    service = f"department-agent-{case.fault_department}"
    compose(case.fault_mode, service, cwd=project_dir)


def restore_fault(case: EvalCase, *, project_dir: Path) -> None:
    assert case.fault_mode is not None and case.fault_department is not None
    service = f"department-agent-{case.fault_department}"
    compose("unpause" if case.fault_mode == "pause" else "start", service, cwd=project_dir)


def execute_case(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    case: EvalCase,
    project_dir: Path,
) -> dict[str, Any]:
    trace_id = f"v11-eval-{case.case_id}-{uuid4()}"
    started = time.perf_counter()
    fault_active = False
    try:
        if case.kind == "fault":
            inject_fault(case, project_dir=project_dir)
            fault_active = True
        response = client.post(
            "/api/v1/chat",
            headers={**headers, "X-Trace-Id": trace_id},
            json={"query": case.query, "session_id": trace_id},
        )
        response.raise_for_status()
        body = cast(dict[str, Any], response.json())
        trace_response = client.get(f"/api/v1/traces/{trace_id}", headers=headers)
        trace_response.raise_for_status()
        trace = cast(dict[str, Any], trace_response.json())
    except Exception as error:
        return {
            "id": case.case_id,
            "kind": case.kind,
            "error": type(error).__name__,
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 2),
        }
    finally:
        if fault_active:
            restore_fault(case, project_dir=project_dir)

    orchestration = cast(dict[str, Any], body.get("orchestration", {}))
    citations = cast(list[dict[str, Any]], body.get("citations", []))
    returned_departments = frozenset(
        str(value) for value in orchestration.get("requested_departments", [])
    )
    failed = cast(list[dict[str, str]], orchestration.get("failed_departments", []))
    failure_reasons = {
        str(item.get("dept_id")): str(item.get("reason")) for item in failed
    }
    route_exact = returned_departments == case.expected_departments
    scope_correct = all(
        str(citation.get("department")) in case.expected_departments for citation in citations
    )
    partial_correct = case.expected_outcome != "partial" or (
        body.get("status") == "SUCCESS"
        and orchestration.get("partial") is True
        and failure_reasons.get(case.fault_department) == case.expected_failure_reason
    )
    success_correct = case.expected_outcome != "success" or (
        body.get("status") == "SUCCESS" and orchestration.get("partial") is False
    )
    return {
        "id": case.case_id,
        "kind": case.kind,
        "expected_departments": sorted(case.expected_departments),
        "selected_departments": sorted(returned_departments),
        "route_set_exact": route_exact,
        "status": body.get("status"),
        "partial": orchestration.get("partial"),
        "failed_departments": failed,
        "citation_departments": sorted({str(item.get("department")) for item in citations}),
        "citation_scope_correct": scope_correct,
        "success_correct": success_correct,
        "partial_correct": partial_correct,
        "trace_id": trace_id,
        "child_trace_ids": trace.get("child_trace_ids", []),
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 2),
    }


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def metrics_for(results: list[dict[str, Any]]) -> dict[str, object]:
    completed = [item for item in results if "error" not in item]
    cross = [item for item in completed if item["kind"] == "cross"]
    fault = [item for item in completed if item["kind"] == "fault"]
    timeout = [
        item
        for item in fault
        if any(failure.get("reason") == "timeout" for failure in item["failed_departments"])
    ]
    return {
        "evaluation_type": "INTEGRATION_FIXTURE",
        "case_count": len(results),
        "executed_case_count": len(completed),
        "route_set_exact_match": ratio(
            sum(bool(item["route_set_exact"]) for item in completed), len(completed)
        ),
        "cross_department_completion_rate": ratio(
            sum(bool(item["success_correct"]) for item in cross), len(cross)
        ),
        "partial_response_correctness": ratio(
            sum(bool(item["partial_correct"]) for item in fault), len(fault)
        ),
        "citation_department_scope_accuracy": ratio(
            sum(bool(item["citation_scope_correct"]) for item in completed), len(completed)
        ),
        "timeout_isolation_success_rate": ratio(
            sum(bool(item["partial_correct"]) for item in timeout), 1
        ),
        "case_errors": [item for item in results if "error" in item],
    }


def write_artifacts(
    *,
    run_dir: Path,
    args: argparse.Namespace,
    fixture: Path,
    cases: list[EvalCase],
    results: list[dict[str, Any]],
    metrics: dict[str, object],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "evaluation_type": "INTEGRATION_FIXTURE",
                "base_url": args.base_url,
                "fixture": str(fixture.relative_to(ROOT)),
                "fixture_sha256": digest,
                "generated_at": datetime.now(UTC).isoformat(),
                "provider_note": "Pi Faux runtime; real Compose retrieval and service transport.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "fixture": str(fixture.relative_to(ROOT)),
                "sha256": digest,
                "cases": [case.case_id for case in cases],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (run_dir / "raw_results.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rows = "\n".join(
        "| {id} | {kind} | {status} | {partial} | {route} | {scope} | {elapsed} |".format(
            id=result["id"],
            kind=result["kind"],
            status=result.get("status", result.get("error", "ERROR")),
            partial=result.get("partial", "-"),
            route=result.get("route_set_exact", False),
            scope=result.get("citation_scope_correct", False),
            elapsed=result["elapsed_ms"],
        )
        for result in results
    )
    (run_dir / "report.md").write_text(
        "# V1.1 Multi-Agent Fixture Evaluation\n\n"
        "This is an `INTEGRATION_FIXTURE` result. It uses real Compose HTTP services and "
        "real Mongo/OpenSearch/Milvus/Redis retrieval, while Pi is configured with its "
        "deterministic Faux transport. It is not a public-policy benchmark or an external "
        "LLM quality claim.\n\n"
        "| Case | Kind | Status | Partial | Route exact | Citation scope | Elapsed ms |\n"
        "| --- | --- | --- | --- | --- | --- | ---: |\n"
        f"{rows}\n\n## Metrics\n\n```json\n"
        f"{json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True)}\n```\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if not args.base_url:
        raise SystemExit("--base-url or V11_MULTI_AGENT_BASE_URL is required")
    fixture = args.fixture.resolve()
    cases = load_cases(fixture)
    run_id = f"v11_multi_agent_eval_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = args.runs_dir.resolve() / run_id
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=45) as client:
        headers = authenticate(client, email=args.email, password=args.password)
        results = [
            execute_case(client, headers=headers, case=case, project_dir=args.compose_project_dir)
            for case in cases
        ]
    metrics = metrics_for(results)
    write_artifacts(
        run_dir=run_dir,
        args=args,
        fixture=fixture,
        cases=cases,
        results=results,
        metrics=metrics,
    )
    print(f"V1.1 multi-agent fixture artifacts: {run_dir}")
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    required = (
        metrics["executed_case_count"] == 12
        and metrics["route_set_exact_match"] == 1.0
        and metrics["cross_department_completion_rate"] == 1.0
        and metrics["partial_response_correctness"] == 1.0
        and metrics["citation_department_scope_accuracy"] == 1.0
        and metrics["timeout_isolation_success_rate"] == 1.0
    )
    return 0 if required else 1


if __name__ == "__main__":
    sys.exit(main())
