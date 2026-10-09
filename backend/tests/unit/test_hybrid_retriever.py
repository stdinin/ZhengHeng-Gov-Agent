from dataclasses import dataclass, field

import pytest

from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.citations import Evidence
from backend.app.retrieval.hybrid import HybridEvidenceRetriever
from backend.app.retrieval.reranker import ScoredEvidence
from backend.app.retrieval.rrf import RankedCandidate


def _candidate(chunk_id: str, rank: int) -> RankedCandidate:
    return RankedCandidate(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        version_id=f"ver-{chunk_id}",
        rank=rank,
    )


def _evidence(chunk_id: str, status: DocumentVersionStatus) -> Evidence:
    return Evidence(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        version_id=f"ver-{chunk_id}",
        title=f"政策 {chunk_id}",
        department="tax",
        status=status,
        text=f"policy text {chunk_id}",
    )


@dataclass
class StubBM25:
    calls: list[tuple[str, tuple[str, ...], int]] = field(default_factory=list)

    async def search(
        self, query: str, *, department_ids: tuple[str, ...], limit: int
    ) -> list[RankedCandidate]:
        self.calls.append((query, department_ids, limit))
        return [_candidate("archived", 1), _candidate("active-a", 2), _candidate("active-b", 3)]


@dataclass
class StubDense:
    calls: list[tuple[list[float], list[str] | None, int]] = field(default_factory=list)

    async def search(
        self, vector: list[float], *, department_ids: list[str] | None, limit: int
    ) -> list[RankedCandidate]:
        self.calls.append((vector, department_ids, limit))
        return [_candidate("active-a", 1), _candidate("archived", 2), _candidate("active-b", 3)]


@dataclass
class StubEmbedder:
    calls: list[str] = field(default_factory=list)

    async def embed(self, query: str) -> list[float]:
        self.calls.append(query)
        return [1.0, 0.0]


@dataclass
class RecordingEvidenceStore:
    events: list[str] = field(default_factory=list)
    rerank_calls: list[list[RankedCandidate]] = field(default_factory=list)
    canonical_calls: list[list[RankedCandidate]] = field(default_factory=list)

    async def get_evidence_for_rerank(
        self, candidates: list[RankedCandidate]
    ) -> list[Evidence]:
        self.events.append("rerank-input")
        self.rerank_calls.append(candidates)
        return [
            _evidence(
                candidate.chunk_id,
                (
                    DocumentVersionStatus.ARCHIVED
                    if candidate.chunk_id == "archived"
                    else DocumentVersionStatus.ACTIVE
                ),
            )
            for candidate in candidates
        ]

    async def get_canonical_evidence(
        self, candidates: list[RankedCandidate]
    ) -> list[Evidence]:
        self.events.append("canonical")
        self.canonical_calls.append(candidates)
        return [
            _evidence(candidate.chunk_id, DocumentVersionStatus.ACTIVE)
            for candidate in candidates
            if candidate.chunk_id != "archived"
        ]


@dataclass
class ReverseTestReranker:
    events: list[str]
    calls: list[tuple[str, list[ScoredEvidence], int]] = field(default_factory=list)

    async def rerank(
        self, query: str, candidates: list[ScoredEvidence], *, limit: int
    ) -> list[ScoredEvidence]:
        self.events.append("rerank")
        self.calls.append((query, candidates, limit))
        return list(reversed(candidates))[:limit]


@pytest.mark.asyncio
async def test_hybrid_retriever_orders_rrf_rerank_then_canonical_recheck_with_independent_caps(
) -> None:
    bm25 = StubBM25()
    dense = StubDense()
    embedder = StubEmbedder()
    store = RecordingEvidenceStore()
    reranker = ReverseTestReranker(store.events)
    retriever = HybridEvidenceRetriever(
        bm25=bm25,
        dense=dense,
        embedder=embedder,
        canonical_store=store,
        reranker=reranker,
        bm25_top_k=5,
        dense_top_k=4,
        fused_top_k=3,
        rerank_top_n=2,
        final_context_top_k=1,
    )

    result = await retriever.retrieve_with_trace(
        queries=["tax relief"], department_ids=["tax"], limit=6
    )

    assert [item.chunk_id for item in result.evidence] == ["active-a"]
    assert store.events == ["rerank-input", "rerank", "canonical"]
    assert bm25.calls == [("tax relief", ("tax",), 5)]
    assert dense.calls == [([1.0, 0.0], ["tax"], 4)]
    assert len(store.rerank_calls[0]) == 3
    assert len(reranker.calls[0][1]) == 2
    assert [item.chunk_id for item in store.canonical_calls[0]] == ["archived", "active-a"]
    assert result.trace.fused_candidate_count == 3
    assert result.trace.rerank_input_count == 2
    assert result.trace.reranked_candidate_count == 2
    assert result.trace.canonical_candidate_count == 1
    assert result.trace.reranker_skipped is False


@pytest.mark.asyncio
async def test_disabled_reranker_bypasses_scoring_and_records_the_explicit_trace_flag() -> None:
    store = RecordingEvidenceStore()
    retriever = HybridEvidenceRetriever(
        bm25=StubBM25(),
        dense=StubDense(),
        embedder=StubEmbedder(),
        canonical_store=store,
        reranker=None,
        reranker_enabled=False,
        fused_top_k=3,
        rerank_top_n=2,
        final_context_top_k=8,
    )

    result = await retriever.retrieve_with_trace(
        queries=["tax relief"], department_ids=["tax"], limit=8
    )

    assert result.trace.reranker_skipped is True
    assert result.trace.reranked_candidate_count == 0
    assert store.events == ["rerank-input", "canonical"]
    assert [item.chunk_id for item in result.evidence] == ["active-a"]
