from collections.abc import Sequence


def recall_at_k(ranked_ids: Sequence[str], gold_ids: set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive.")
    if not gold_ids:
        return 0.0
    return len(set(ranked_ids[:k]) & gold_ids) / len(gold_ids)


def reciprocal_rank(ranked_ids: Sequence[str], gold_ids: set[str]) -> float:
    for index, item in enumerate(ranked_ids, start=1):
        if item in gold_ids:
            return 1 / index
    return 0.0


def mean_reciprocal_rank(
    ranked_lists: Sequence[Sequence[str]], gold_sets: Sequence[set[str]]
) -> float:
    if len(ranked_lists) != len(gold_sets):
        raise ValueError("ranked_lists and gold_sets must have the same length.")
    if not ranked_lists:
        return 0.0
    return sum(
        reciprocal_rank(ranked_ids, gold_ids)
        for ranked_ids, gold_ids in zip(ranked_lists, gold_sets, strict=True)
    ) / len(ranked_lists)


def citation_precision(
    *, cited_chunk_ids: Sequence[str], valid_chunk_ids: set[str], archived_chunk_ids: set[str]
) -> float:
    if not cited_chunk_ids:
        return 0.0
    valid = sum(
        chunk_id in valid_chunk_ids and chunk_id not in archived_chunk_ids
        for chunk_id in cited_chunk_ids
    )
    return valid / len(cited_chunk_ids)
