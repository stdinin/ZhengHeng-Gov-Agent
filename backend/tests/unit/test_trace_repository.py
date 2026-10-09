from datetime import UTC, datetime

from backend.app.storage.trace_repository import MongoTraceStore


def test_mongo_trace_store_rehydrates_full_trace_state() -> None:
    now = datetime.now(UTC)
    trace = MongoTraceStore._from_document(
        {
            "_id": "trace_1",
            "user_id": "user_1",
            "session_id": "session_1",
            "query": "增值税优惠",
            "nodes": [],
            "status": "SUCCESS",
            "answer": "答复 [C1]",
            "created_at": now,
            "updated_at": now,
            "normalized_query": "增值税优惠",
            "intent": {"intent": "POLICY_QUERY"},
            "rewritten_queries": ["增值税优惠"],
            "department_routes": [{"department_id": "dept_tax", "score": 0.9}],
            "retrieval_hits": ["chunk_1"],
            "citations": [{"id": "C1", "chunk_id": "chunk_1"}],
            "verification": {"passed": True, "warnings": []},
            "retry_count": 1,
            "errors": ["first attempt unsupported"],
            "timings_ms": {"total": 12.3},
        }
    )

    assert trace.normalized_query == "增值税优惠"
    assert trace.department_routes[0]["department_id"] == "dept_tax"
    assert trace.citations[0]["id"] == "C1"
    assert trace.retry_count == 1
    assert trace.timings_ms == {"total": 12.3}
