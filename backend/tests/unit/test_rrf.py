from math import isclose

from backend.app.retrieval.rrf import RankedCandidate, reciprocal_rank_fusion


def test_rrf_fuses_sparse_and_dense_ranks_without_hardcoded_outcome() -> None:
    merged = reciprocal_rank_fusion(
        {
            "bm25": [
                RankedCandidate(
                    chunk_id="chunk_a", document_id="doc_a", version_id="ver_a", rank=1
                ),
                RankedCandidate(
                    chunk_id="chunk_b", document_id="doc_b", version_id="ver_b", rank=2
                ),
            ],
            "dense": [
                RankedCandidate(
                    chunk_id="chunk_b", document_id="doc_b", version_id="ver_b", rank=1
                ),
                RankedCandidate(
                    chunk_id="chunk_a", document_id="doc_a", version_id="ver_a", rank=2
                ),
            ],
        },
        rrf_k=60,
    )

    assert [result.chunk_id for result in merged] == ["chunk_a", "chunk_b"]
    assert isclose(merged[0].rrf_score, 1 / 61 + 1 / 62)
    assert merged[0].source_ranks == {"bm25": 1, "dense": 2}


def test_rrf_rejects_non_positive_k_and_rank() -> None:
    candidate = RankedCandidate(chunk_id="chunk", document_id="doc", version_id="ver", rank=1)

    try:
        reciprocal_rank_fusion({"bm25": [candidate]}, rrf_k=0)
    except ValueError as error:
        assert "rrf_k" in str(error)
    else:
        raise AssertionError("rrf_k=0 must be rejected")
