from collections import defaultdict

_DAG_NODE_LABELS = frozenset({"Intent", "Rewrite", "Route", "Retrieve", "Answer", "Verify"})


class MetricsRegistry:
    """Small in-process Prometheus exposition registry fed only by observed application events."""

    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._latencies: defaultdict[str, list[float]] = defaultdict(list)
        for name in (
            "zh_chat_requests_total",
            "zh_chat_errors_total",
            "zh_abstain_total",
            "zh_verifier_fail_total",
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
        if node not in _DAG_NODE_LABELS:
            raise ValueError("Prometheus node labels must use a fixed DAG node.")
        self._latencies[f'zh_node_latency_seconds{{node="{node}"}}'].append(latency_seconds)

    def record_verification(self, *, passed: bool) -> None:
        if not passed:
            self._counters["zh_verifier_fail_total"] += 1

    def increment(self, name: str) -> None:
        self._counters[name] += 1

    def render_prometheus(self) -> str:
        lines = [f"{name} {value}" for name, value in sorted(self._counters.items())]
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


def _split_metric_labels(metric: str) -> tuple[str, str]:
    if "{" not in metric:
        return metric, ""
    name, labels = metric.split("{", maxsplit=1)
    return name, "{" + labels
