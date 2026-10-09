from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    chunk_id: str
    document_id: str
    version_id: str
    rank: int
    raw_score: float | None = None

    def __post_init__(self) -> None:
        if self.rank <= 0:
            raise ValueError("Candidate rank must be positive.")


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    chunk_id: str
    document_id: str
    version_id: str
    rrf_score: float
    source_ranks: dict[str, int]


def reciprocal_rank_fusion(
    result_lists: Mapping[str, Sequence[RankedCandidate]], *, rrf_k: int
) -> list[FusedCandidate]:
    """Merge ranked lists with deterministic standard RRF; no retrieval result is fabricated."""

    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive.")
    accumulators: dict[str, FusedCandidate] = {}
    for source, candidates in result_lists.items():
        for candidate in candidates:
            existing = accumulators.get(candidate.chunk_id)
            contribution = 1 / (rrf_k + candidate.rank)
            if existing is None:
                accumulators[candidate.chunk_id] = FusedCandidate(
                    chunk_id=candidate.chunk_id,
                    document_id=candidate.document_id,
                    version_id=candidate.version_id,
                    rrf_score=contribution,
                    source_ranks={source: candidate.rank},
                )
            else:
                if (
                    existing.document_id != candidate.document_id
                    or existing.version_id != candidate.version_id
                ):
                    raise ValueError(f"Chunk identity conflict for {candidate.chunk_id}.")
                source_ranks = {**existing.source_ranks, source: candidate.rank}
                accumulators[candidate.chunk_id] = FusedCandidate(
                    chunk_id=existing.chunk_id,
                    document_id=existing.document_id,
                    version_id=existing.version_id,
                    rrf_score=existing.rrf_score + contribution,
                    source_ranks=source_ranks,
                )
    return sorted(accumulators.values(), key=lambda item: (-item.rrf_score, item.chunk_id))
