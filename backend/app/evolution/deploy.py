import hashlib
import math
from dataclasses import dataclass

from backend.app.evolution.replay import ReplayMetrics


def stable_bucket(user_id: str, session_id: str, strategy_id: str, version: int) -> int:
    payload = f"{user_id}:{session_id}:{strategy_id}:{version}".encode()
    return int(hashlib.sha256(payload).hexdigest()[:8], 16) % 100


def is_treatment(
    *, user_id: str, session_id: str, strategy_id: str, version: int, rollout_percent: int
) -> bool:
    if not 0 <= rollout_percent <= 100:
        raise ValueError("rollout_percent must be between 0 and 100.")
    return stable_bucket(user_id, session_id, strategy_id, version) < rollout_percent


@dataclass(frozen=True, slots=True)
class RollbackDecision:
    rollback: bool
    reasons: list[str]


def should_rollback(
    *,
    control: ReplayMetrics,
    treatment: ReplayMetrics,
    control_n: int,
    treatment_n: int,
    manual: bool = False,
) -> RollbackDecision:
    if manual:
        return RollbackDecision(rollback=True, reasons=["manual rollback"])
    if min(control_n, treatment_n) < 50:
        return RollbackDecision(rollback=False, reasons=["insufficient arm sample size"])
    reasons: list[str] = []
    success_drop = control.success_rate - treatment.success_rate
    if success_drop >= 0.05 and _two_proportion_p_value(
        control.success_rate, control_n, treatment.success_rate, treatment_n
    ) < 0.05:
        reasons.append("statistically significant success-rate degradation")
    if treatment.citation_error_rate - control.citation_error_rate >= 0.02:
        reasons.append("citation error rate increased by at least two percentage points")
    if treatment.stale_policy_errors > 0 and control.stale_policy_errors == 0:
        reasons.append("treatment introduced stale policy errors")
    if treatment.p95_ms > control.p95_ms * 1.3:
        reasons.append("p95 latency increased by more than thirty percent")
    return RollbackDecision(rollback=bool(reasons), reasons=reasons)


def _two_proportion_p_value(rate_a: float, n_a: int, rate_b: float, n_b: int) -> float:
    pooled = (rate_a * n_a + rate_b * n_b) / (n_a + n_b)
    standard_error = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if standard_error == 0:
        return 1.0
    z_score = abs(rate_a - rate_b) / standard_error
    return math.erfc(z_score / math.sqrt(2))
