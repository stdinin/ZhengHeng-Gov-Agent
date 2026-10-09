from pathlib import Path

from scripts.run_public_eval import (
    _load_evaluate_checkpoint,
    _save_evaluate_checkpoint,
)


def test_public_eval_checkpoint_round_trips_atomically(tmp_path: Path) -> None:
    path = tmp_path / "evaluate_checkpoint.json"
    predictions = {"bm25": {"case-1": ["chunk-1"]}}
    latencies = {"bm25": [12.5]}
    raw_predictions: list[dict[str, object]] = [{"case_id": "case-1"}]
    retrieval_rows: list[dict[str, object]] = [{"case_id": "case-1"}]
    trace_rows: list[dict[str, object]] = [{"case_id": "case-1"}]

    _save_evaluate_checkpoint(
        path,
        predictions=predictions,
        latencies=latencies,
        raw_predictions=raw_predictions,
        retrieval_rows=retrieval_rows,
        trace_rows=trace_rows,
    )

    checkpoint = _load_evaluate_checkpoint(path)

    assert checkpoint is not None
    assert checkpoint["complete"] is False
    assert checkpoint["completed_case_ids"] == ["case-1"]
    assert checkpoint["predictions"] == predictions
    assert not path.with_name("evaluate_checkpoint.json.tmp").exists()
