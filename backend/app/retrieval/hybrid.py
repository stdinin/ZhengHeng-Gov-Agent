"""Real hybrid retrieval composition with explicit, traceable stage boundaries."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from inspect import isawaitable
from typing import Protocol

from backend.app.config import Settings
from backend.app.harness.citations import Evidence
from backend.app.ingestion.lifecycle import can_be_fact_evidence
from backend.app.retrieval.embedding import (
    EmbeddingProviderError,
    QueryEmbedder,
    build_embedding_provider,
)
from backend.app.retrieval.reranker import (
    CrossEncoderReranker,
    EvidenceReranker,
    ScoredEvidence,
)
from backend.app.retrieval.rrf import FusedCandidate, RankedCandidate, reciprocal_rank_fusion


class SparseSearcher(Protocol):
    async def search(
        self, query: str, *, department_ids: Sequence[str] = (), limit: int = 40
    ) -> list[RankedCandidate]: ...


class DenseSearcher(Protocol):
    async def search(
        self, vector: list[float], *, department_ids: list[str] | None = None, limit: int = 40
    ) -> list[RankedCandidate]: ...


class CanonicalEvidenceStore(Protocol):
    """Mongo fact-plane reads split so reranking precedes lifecycle/pointer validation."""

    async def get_evidence_for_rerank(
        self, candidates: list[RankedCandidate]
    ) -> list[Evidence]: ...

    async def get_canonical_evidence(
        self, candidates: list[RankedCandidate]
    ) -> list[Evidence]: ...


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    bm25_candidate_count: int
    dense_candidate_count: int
    fused_candidate_count: int
    rerank_input_count: int
    reranked_candidate_count: int
    canonical_candidate_count: int
    reranker_skipped: bool


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    evidence: list[Evidence]
    trace: RetrievalTrace


class HybridEvidenceRetriever:
    """BM25 -> dense -> RRF -> cross-encoder -> canonical active/current re-check."""

    def __init__(
        self,
        *,
        bm25: SparseSearcher,
        dense: DenseSearcher,
        embedder: QueryEmbedder,
        canonical_store: CanonicalEvidenceStore,
        reranker: EvidenceReranker | None,
        reranker_enabled: bool = True,
        rrf_k: int = 60,
        bm25_top_k: int = 40,
        dense_top_k: int = 40,
        fused_top_k: int = 60,
        rerank_top_n: int = 30,
        final_context_top_k: int = 8,
    ) -> None:
        if reranker_enabled and reranker is None:
            raise ValueError("A real reranker is required unless RERANKER_ENABLED=false.")
        caps = {
            "rrf_k": rrf_k,
            "bm25_top_k": bm25_top_k,
            "dense_top_k": dense_top_k,
            "fused_top_k": fused_top_k,
            "rerank_top_n": rerank_top_n,
            "final_context_top_k": final_context_top_k,
        }
        invalid = [name for name, value in caps.items() if value <= 0]
        if invalid:
            raise ValueError(f"Positive retrieval caps required: {', '.join(invalid)}")
        self._bm25 = bm25
        self._dense = dense
        self._embedder = embedder
        self._canonical_store = canonical_store
        self._reranker = reranker
        self._reranker_enabled = reranker_enabled
        self._rrf_k = rrf_k
        self._bm25_top_k = bm25_top_k
        self._dense_top_k = dense_top_k
        self._fused_top_k = fused_top_k
        self._rerank_top_n = rerank_top_n
        self._final_context_top_k = final_context_top_k

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        bm25: SparseSearcher,
        dense: DenseSearcher,
        canonical_store: CanonicalEvidenceStore,
    ) -> "HybridEvidenceRetriever":
        """Build the production composition without tying embeddings to ``LLM_MODE``."""

        return cls(
            bm25=bm25,
            dense=dense,
            embedder=build_embedding_provider(settings),
            canonical_store=canonical_store,
            reranker=(
                CrossEncoderReranker(model_name=settings.reranker_model)
                if settings.reranker_enabled
                else None
            ),
            reranker_enabled=settings.reranker_enabled,
            rrf_k=settings.rrf_k,
            bm25_top_k=settings.bm25_top_k,
            dense_top_k=settings.dense_top_k,
            fused_top_k=settings.fused_top_k,
            rerank_top_n=settings.rerank_top_n,
            final_context_top_k=settings.final_context_top_k,
        )

    async def retrieve(
        self, *, queries: list[str], department_ids: list[str], limit: int
    ) -> list[Evidence]:
        result = await self.retrieve_with_trace(
            queries=queries, department_ids=department_ids, limit=limit
        )
        return result.evidence

    async def close(self) -> None:
        """Release network-backed retrieval clients owned by this composition."""

        failures: list[Exception] = []
        for resource in (self._bm25, self._dense, self._embedder, self._reranker):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                outcome = close()
                if isawaitable(outcome):
                    await outcome
            except Exception as error:
                failures.append(error)
        if failures:
            raise RuntimeError("One or more retrieval resources failed to close.") from failures[0]

    async def retrieve_with_trace(
        self, *, queries: list[str], department_ids: list[str], limit: int
    ) -> RetrievalResult:
        if limit <= 0:
            raise ValueError("limit must be positive.")
        normalized_queries = list(
            dict.fromkeys(" ".join(query.split()) for query in queries if query.strip())
        )
        if not normalized_queries:
            return RetrievalResult(
                evidence=[],
                trace=RetrievalTrace(0, 0, 0, 0, 0, 0, not self._reranker_enabled),
            )

        result_lists: dict[str, list[RankedCandidate]] = {}
        bm25_count = 0
        dense_count = 0
        for index, query in enumerate(normalized_queries):
            vector = await self._embedder.embed(query)
            sparse, dense = await asyncio.gather(
                self._bm25.search(
                    query, department_ids=tuple(department_ids), limit=self._bm25_top_k
                ),
                self._dense.search(vector, department_ids=department_ids, limit=self._dense_top_k),
            )
            bm25_count += len(sparse)
            dense_count += len(dense)
            result_lists[f"bm25:{index}"] = sparse
            result_lists[f"dense:{index}"] = dense

        fused = reciprocal_rank_fusion(result_lists, rrf_k=self._rrf_k)[: self._fused_top_k]
        if not fused:
            return RetrievalResult(
                evidence=[],
                trace=RetrievalTrace(
                    bm25_count,
                    dense_count,
                    0,
                    0,
                    0,
                    0,
                    not self._reranker_enabled,
                ),
            )

        fused_candidates = [
            self._to_ranked_candidate(item, rank) for rank, item in enumerate(fused, 1)
        ]
        rerank_evidence = await self._canonical_store.get_evidence_for_rerank(fused_candidates)
        scored = self._score_rerank_evidence(fused, rerank_evidence)[: self._rerank_top_n]

        reranker_skipped = not self._reranker_enabled
        if self._reranker_enabled:
            if self._reranker is None:  # Defensive guard for a misconfigured construction path.
                raise ValueError("A real reranker is required unless RERANKER_ENABLED=false.")
            reranked = await self._reranker.rerank(
                " ".join(normalized_queries), scored, limit=self._rerank_top_n
            )
            reranked_count = len(reranked)
        else:
            # This bypass preserves RRF order and never manufactures a reranker score.
            reranked = scored
            reranked_count = 0

        canonical_candidates = [
            RankedCandidate(
                chunk_id=item.evidence.chunk_id,
                document_id=item.evidence.document_id,
                version_id=item.evidence.version_id,
                rank=rank,
            )
            for rank, item in enumerate(reranked, start=1)
        ]
        canonical = await self._canonical_store.get_canonical_evidence(canonical_candidates)
        evidence = [item for item in canonical if can_be_fact_evidence(item.status)]
        evidence = evidence[: min(limit, self._final_context_top_k)]
        return RetrievalResult(
            evidence=evidence,
            trace=RetrievalTrace(
                bm25_candidate_count=bm25_count,
                dense_candidate_count=dense_count,
                fused_candidate_count=len(fused),
                rerank_input_count=len(scored),
                reranked_candidate_count=reranked_count,
                canonical_candidate_count=len(canonical),
                reranker_skipped=reranker_skipped,
            ),
        )

    @staticmethod
    def _to_ranked_candidate(item: FusedCandidate, rank: int) -> RankedCandidate:
        return RankedCandidate(
            chunk_id=item.chunk_id,
            document_id=item.document_id,
            version_id=item.version_id,
            rank=rank,
            raw_score=item.rrf_score,
        )

    @staticmethod
    def _score_rerank_evidence(
        fused: list[FusedCandidate], rerank_evidence: list[Evidence]
    ) -> list[ScoredEvidence]:
        fused_by_identity = {
            (item.chunk_id, item.document_id, item.version_id): item for item in fused
        }
        return [
            ScoredEvidence(evidence=item, rrf_score=fused_by_identity[identity].rrf_score)
            for item in rerank_evidence
            if (identity := (item.chunk_id, item.document_id, item.version_id)) in fused_by_identity
        ]


__all__ = [
    "CanonicalEvidenceStore",
    "EmbeddingProviderError",
    "HybridEvidenceRetriever",
    "QueryEmbedder",
    "RetrievalResult",
    "RetrievalTrace",
]
