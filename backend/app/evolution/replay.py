from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ReplayMetrics:
    success_rate: float
    citation_error_rate: float
    stale_policy_errors: int
    p95_ms: float


@dataclass(frozen=True, slots=True)
class ReplayGateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_replay_gate(
    *,
    baseline: ReplayMetrics,
    candidate: ReplayMetrics,
    target_badcases_resolved: int,
) -> ReplayGateResult:
    reasons: list[str] = []
    if candidate.success_rate < baseline.success_rate - 0.01:
        reasons.append("success rate decreased by more than one percentage point")
    if candidate.citation_error_rate > baseline.citation_error_rate:
        reasons.append("citation error rate increased")
    if candidate.stale_policy_errors > baseline.stale_policy_errors:
        reasons.append("stale policy errors increased")
    if candidate.p95_ms > baseline.p95_ms * 1.2:
        reasons.append("p95 latency increased by more than twenty percent")
    if target_badcases_resolved < 1:
        reasons.append("no target bad case was resolved")
    return ReplayGateResult(passed=not reasons, reasons=reasons)
