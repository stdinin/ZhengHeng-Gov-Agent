from backend.app.evolution.deploy import should_rollback, stable_bucket
from backend.app.evolution.models import (
    ActionType,
    ObservationReason,
    StrategyCandidate,
    StrategyStatus,
)
from backend.app.evolution.replay import ReplayMetrics, evaluate_replay_gate


def test_strategy_schema_rejects_executable_or_unknown_actions() -> None:
    candidate = StrategyCandidate.model_validate(
        {
            "id": "strategy_1",
            "version": 1,
            "status": "CANDIDATE",
            "actions": [
                {"action_type": "QUERY_EXPAND", "terms": ["灵活就业"]},
                {"action_type": "TOP_K_ADJUST", "top_k": 12},
            ],
        }
    )

    assert candidate.actions[0].action_type is ActionType.QUERY_EXPAND
    try:
        StrategyCandidate.model_validate(
            {
                "id": "unsafe",
                "version": 1,
                "status": "CANDIDATE",
                "actions": [{"action_type": "SHELL", "command": "rm -rf /"}],
            }
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Executable actions must not validate as a strategy.")


def test_strategy_dsl_accepts_goal_action_type_shape_and_full_taxonomy() -> None:
    candidate = StrategyCandidate.model_validate(
        {
            "id": "strategy_goal_shape",
            "version": 1,
            "status": "CANDIDATE",
            "actions": [
                {
                    "type": "TOP_K_ADJUST",
                    "dense_top_k": 60,
                    "bm25_top_k": 60,
                }
            ],
        }
    )

    assert candidate.actions[0].action_type is ActionType.TOP_K_ADJUST
    assert ObservationReason.INTENT_ERROR.value == "INTENT_ERROR"
    assert StrategyStatus.SHADOW.value == "SHADOW"


def test_stable_bucket_is_deterministic_and_in_rollout_range() -> None:
    first = stable_bucket("user_1", "session_1", "strategy_1", 2)

    assert first == stable_bucket("user_1", "session_1", "strategy_1", 2)
    assert 0 <= first < 100


def test_replay_gate_and_rollback_apply_documented_thresholds() -> None:
    passed = evaluate_replay_gate(
        baseline=ReplayMetrics(
            success_rate=0.80,
            citation_error_rate=0.01,
            stale_policy_errors=0,
            p95_ms=100,
        ),
        candidate=ReplayMetrics(
            success_rate=0.80,
            citation_error_rate=0.01,
            stale_policy_errors=0,
            p95_ms=119,
        ),
        target_badcases_resolved=1,
    )
    rollback = should_rollback(
        control=ReplayMetrics(
            success_rate=0.85,
            citation_error_rate=0.00,
            stale_policy_errors=0,
            p95_ms=100,
        ),
        treatment=ReplayMetrics(
            success_rate=0.79,
            citation_error_rate=0.03,
            stale_policy_errors=1,
            p95_ms=131,
        ),
        control_n=50,
        treatment_n=50,
    )

    assert passed.passed is True
    assert rollback.rollback is True
    assert StrategyStatus.ROLLED_BACK.value == "ROLLED_BACK"
