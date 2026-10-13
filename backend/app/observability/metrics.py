from collections import defaultdict
from typing import Any

from backend.app.observability.tracing import TraceRecord

_DAG_NODE_LABELS = frozenset({"Intent", "Rewrite", "Route", "Retrieve", "Answer", "Verify"})
_RUNTIME_NODES = frozenset(
    {"intent", "rewrite", "route", "answer", "verify", "aggregate", "reflect"}
)
_RUNTIME_BACKENDS = frozenset(
    {"pi", "fake", "openai_compatible", "legacy", "safe_fallback", "unknown"}
)
_ORCHESTRATION_MODES = frozenset({"single", "multi", "abstain"})
_OUTCOMES = frozenset(
    {
        "success",
        "abstain",
        "timeout",
        "no_evidence",
        "retrieval_error",
        "verification_failed",
        "runtime_error",
        "client_error",
        "error",
    }
)
_FORBIDDEN_LABELS = frozenset(
    {"query", "user_id", "trace_id", "name", "phone", "raw_document_title"}
)
_TRACE_NODE_TO_RUNTIME = {
    "Intent": "intent",
    "Rewrite": "rewrite",
    "Route": "route",
    "Answer": "answer",
    "Verify": "verify",
    "Aggregate": "aggregate",
    "DepartmentAnswer": "answer",
    "DepartmentVerify": "verify",
}


def is_fixed_dag_node(node: str) -> bool:
    """Return whether a trace timing is safe to expose as a Prometheus label."""

    return node in _DAG_NODE_LABELS


class MetricsRegistry:
    """Small in-process Prometheus exposition registry fed only by observed application events."""

    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._latencies: defaultdict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}
        for name in (
            "zh_chat_requests_total",
            "zh_chat_errors_total",
            "zh_abstain_total",
            "zh_verifier_fail_total",
            "zhengheng_orchestrator_partial_total",
        ):
            self._counters[name] = 0

    def record_chat(self, *, status: str, latency_seconds: float) -> None:
        self._validate_latency(latency_seconds)
        self._counters["zh_chat_requests_total"] += 1
        self._latencies["zh_chat_latency_seconds"].append(latency_seconds)
        if status != "SUCCESS":
            self._counters["zh_chat_errors_total"] += 1
        if status == "ABSTAIN":
            self._counters["zh_abstain_total"] += 1

    def record_node(self, *, node: str, latency_seconds: float) -> None:
        self._validate_latency(latency_seconds)
        if not is_fixed_dag_node(node):
            raise ValueError("Prometheus node labels must use a fixed DAG node.")
        self._latencies[f'zh_node_latency_seconds{{node="{node}"}}'].append(latency_seconds)

    def record_verification(self, *, passed: bool) -> None:
        if not passed:
            self._counters["zh_verifier_fail_total"] += 1

    def increment(self, name: str) -> None:
        self._counters[name] += 1

    def record_runtime_event(self, *, trace_node: str, event: dict[str, Any]) -> None:
        """Expose a runtime audit using only fixed low-cardinality dimensions."""

        node = _TRACE_NODE_TO_RUNTIME.get(trace_node)
        if node is None or node not in _RUNTIME_NODES:
            return
        backend_used = self._backend(event.get("runtime_backend_used"))
        backend_requested = self._backend(event.get("runtime_backend_requested"))
        fallback = event.get("runtime_fallback_reason")
        status = "fallback" if fallback is not None else "success"
        self._increment_labelled(
            "zhengheng_runtime_invocations_total",
            {"backend": backend_used, "node": node, "status": status},
        )
        latency = event.get("runtime_latency_ms")
        if isinstance(latency, (int, float)) and latency >= 0:
            self._record_labelled_latency(
                "zhengheng_runtime_latency_seconds",
                {"backend": backend_used, "node": node},
                float(latency) / 1_000,
            )
        if fallback is not None:
            self._increment_labelled(
                "zhengheng_runtime_fallback_total",
                {
                    "from_backend": backend_requested,
                    "to_backend": backend_used,
                    "node": node,
                },
            )

    def record_orchestration(
        self, *, mode: str, status: str, fanout: int, partial: bool
    ) -> None:
        safe_mode = mode if mode in _ORCHESTRATION_MODES else "abstain"
        safe_status = self._outcome(status)
        if fanout < 0:
            raise ValueError("Orchestrator fanout cannot be negative.")
        self._increment_labelled(
            "zhengheng_orchestrator_requests_total",
            {"mode": safe_mode, "status": safe_status},
        )
        self._gauges["zhengheng_orchestrator_fanout_size"] = float(fanout)
        if partial:
            self._counters["zhengheng_orchestrator_partial_total"] += 1

    def record_department_agent(
        self, *, dept_id: str, status: str, latency_seconds: float, timeout: bool
    ) -> None:
        self._validate_latency(latency_seconds)
        safe_dept = self._department(dept_id)
        safe_status = self._outcome(status)
        self._increment_labelled(
            "zhengheng_department_agent_calls_total",
            {"dept_id": safe_dept, "status": safe_status},
        )
        self._record_labelled_latency(
            "zhengheng_department_agent_latency_seconds",
            {"dept_id": safe_dept},
            latency_seconds,
        )
        if timeout:
            self._increment_labelled(
                "zhengheng_department_agent_timeout_total", {"dept_id": safe_dept}
            )

    def record_trace_runtime(self, trace: TraceRecord) -> None:
        for node in trace.nodes:
            for event in node.runtime_events:
                self.record_runtime_event(trace_node=node.node, event=event)

    def record_department_trace(self, trace: TraceRecord) -> None:
        if trace.trace_kind != "child" or not trace.dept_id:
            return
        error = trace.errors[0] if trace.errors else ""
        if error == "timeout":
            status = "timeout"
        elif trace.status.value == "SUCCESS":
            status = "success"
        elif error in _OUTCOMES:
            status = error
        else:
            status = "abstain"
        self.record_department_agent(
            dept_id=trace.dept_id,
            status=status,
            latency_seconds=trace.timings_ms.get("total", 0.0) / 1_000,
            timeout=status == "timeout",
        )

    def render_prometheus(self) -> str:
        lines = [f"{name} {value}" for name, value in sorted(self._counters.items())]
        lines.extend(f"{name} {value:.6f}" for name, value in sorted(self._gauges.items()))
        for metric, values in sorted(self._latencies.items()):
            name, labels = _split_metric_labels(metric)
            lines.extend(
                [
                    f"{name}_count{labels} {len(values)}",
                    f"{name}_sum{labels} {sum(values):.6f}",
                ]
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _validate_latency(latency_seconds: float) -> None:
        if latency_seconds < 0:
            raise ValueError("Latency cannot be negative.")

    def _increment_labelled(self, name: str, labels: dict[str, str]) -> None:
        self._counters[_metric_key(name, labels)] += 1

    def _record_labelled_latency(
        self, name: str, labels: dict[str, str], latency_seconds: float
    ) -> None:
        self._validate_latency(latency_seconds)
        self._latencies[_metric_key(name, labels)].append(latency_seconds)

    @staticmethod
    def _backend(value: object) -> str:
        return str(value) if str(value) in _RUNTIME_BACKENDS else "unknown"

    @staticmethod
    def _outcome(value: object) -> str:
        normalized = str(value).lower()
        if normalized == "success":
            return "success"
        if normalized == "abstain":
            return "abstain"
        return normalized if normalized in _OUTCOMES else "error"

    @staticmethod
    def _department(value: str) -> str:
        if not value or len(value) > 64 or not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Department metric label must be a static identifier.")
        return value


def _split_metric_labels(metric: str) -> tuple[str, str]:
    if "{" not in metric:
        return metric, ""
    name, labels = metric.split("{", maxsplit=1)
    return name, "{" + labels


def _metric_key(name: str, labels: dict[str, str]) -> str:
    if set(labels) & _FORBIDDEN_LABELS:
        raise ValueError("PII or high-cardinality metric label is forbidden.")
    rendered = ",".join(f'{key}="{labels[key]}"' for key in sorted(labels))
    return f"{name}{{{rendered}}}"
