from backend.app.evaluation.metrics import (
    citation_precision,
    mean_reciprocal_rank,
    recall_at_k,
)


def test_retrieval_metrics_are_calculated_from_ranked_hits() -> None:
    ranked = ["chunk_9", "chunk_2", "chunk_1"]
    gold = {"chunk_1", "chunk_2"}

    assert recall_at_k(ranked, gold, 1) == 0.0
    assert recall_at_k(ranked, gold, 2) == 0.5
    assert mean_reciprocal_rank([ranked, ["chunk_7"]], [gold, {"chunk_7"}]) == 0.75


def test_citation_precision_refuses_archived_citations() -> None:
    assert citation_precision(
        cited_chunk_ids=["chunk_1", "chunk_archived"],
        valid_chunk_ids={"chunk_1"},
        archived_chunk_ids={"chunk_archived"},
    ) == 0.5
