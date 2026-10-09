import pytest

from backend.app.observability.logging import redact_pii
from backend.app.observability.metrics import MetricsRegistry


def test_trace_redaction_removes_common_pii_patterns() -> None:
    redacted = redact_pii("身份证 11010519491231002X，手机 13800138000，邮箱 user@example.com")

    assert "11010519491231002X" not in redacted
    assert "13800138000" not in redacted
    assert "user@example.com" not in redacted


def test_prometheus_metrics_are_measured_events_not_static_dashboard_values() -> None:
    metrics = MetricsRegistry()
    metrics.record_chat(status="SUCCESS", latency_seconds=0.25)
    metrics.record_node(node="Verify", latency_seconds=0.01)

    payload = metrics.render_prometheus()

    assert "zh_chat_requests_total 1" in payload
    assert "zh_chat_latency_seconds_count 1" in payload
    assert 'zh_node_latency_seconds_count{node="Verify"} 1' in payload
    assert "zh_chat_errors_total 0" in payload
    assert "zh_abstain_total 0" in payload
    assert "zh_verifier_fail_total 0" in payload


def test_prometheus_records_real_verifier_failures() -> None:
    metrics = MetricsRegistry()

    metrics.record_verification(passed=False)

    assert "zh_verifier_fail_total 1" in metrics.render_prometheus()


def test_prometheus_rejects_unbounded_or_pii_node_labels() -> None:
    metrics = MetricsRegistry()

    with pytest.raises(ValueError, match="fixed DAG node"):
        metrics.record_node(node="user@example.com", latency_seconds=0.01)
