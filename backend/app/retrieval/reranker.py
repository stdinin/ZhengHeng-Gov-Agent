"""Cross-encoder reranking for retrieval candidates.

The production adapter loads the configured sentence-transformers CrossEncoder.
It has no lexical or score-fabricating fallback: development must explicitly turn
``RERANKER_ENABLED`` off when the model is intentionally unavailable.
"""

import asyncio
import importlib
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol, cast

from backend.app.harness.citations import Evidence


class RerankerProviderError(RuntimeError):
    """The configured cross-encoder cannot score the supplied candidates."""


class CrossEncoderModel(Protocol):
    def predict(self, sentences: list[tuple[str, str]]) -> Sequence[float]: ...


@dataclass(frozen=True, slots=True)
class ScoredEvidence:
    evidence: Evidence
    rrf_score: float
    rerank_score: float | None = None


class EvidenceReranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[ScoredEvidence], *, limit: int
    ) -> list[ScoredEvidence]: ...


def _load_sentence_transformers_cross_encoder(model_name: str) -> CrossEncoderModel:
    """Load the real CrossEncoder lazily so unrelated API paths do not load a model."""

    try:
        module = importlib.import_module("sentence_transformers")
        cross_encoder_factory = cast(Any, module).CrossEncoder
        kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            # Transformers' meta-device loader can trigger a native access violation
            # while mapping large safetensors with current Windows CPU PyTorch builds.
            # The regular loader uses the same complete weights and avoids that path.
            # Keep FP32 on AVX2 hosts: CPU FP16 is dramatically slower for this model.
            kwargs["automodel_args"] = {
                "low_cpu_mem_usage": False,
                "dtype": "float32",
            }
        return cast(CrossEncoderModel, cross_encoder_factory(model_name, **kwargs))
    except (AttributeError, ImportError, OSError, RuntimeError) as error:
        raise RerankerProviderError(
            f"Unable to load cross-encoder model {model_name!r}. "
            "Set RERANKER_ENABLED=false only for an explicit development bypass."
        ) from error


class CrossEncoderReranker:
    """Scores query-document pairs with the configured BGE-compatible cross-encoder."""

    def __init__(
        self,
        *,
        model_name: str,
        prediction_batch_size: int = 8,
        model_loader: Callable[[str], CrossEncoderModel] = (
            _load_sentence_transformers_cross_encoder
        ),
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be blank.")
        if prediction_batch_size <= 0:
            raise ValueError("prediction_batch_size must be positive.")
        self._model_name = model_name
        self._prediction_batch_size = prediction_batch_size
        self._model_loader = model_loader
        self._model: CrossEncoderModel | None = None
        self._model_lock = asyncio.Lock()

    async def rerank(
        self, query: str, candidates: list[ScoredEvidence], *, limit: int
    ) -> list[ScoredEvidence]:
        if not query.strip():
            raise ValueError("query must not be blank.")
        if limit <= 0:
            raise ValueError("limit must be positive.")
        if not candidates:
            return []
        model = await self._get_model()
        pairs = [
            (query, f"{candidate.evidence.title}\n{candidate.evidence.text}")
            for candidate in candidates
        ]
        try:
            scores: list[float] = []
            for offset in range(0, len(pairs), self._prediction_batch_size):
                batch = pairs[offset : offset + self._prediction_batch_size]
                raw_scores = await asyncio.to_thread(model.predict, batch)
                scores.extend(float(score) for score in raw_scores)
        except (TypeError, ValueError, OSError, RuntimeError) as error:
            raise RerankerProviderError("Cross-encoder reranking failed.") from error
        if len(scores) != len(candidates):
            raise RerankerProviderError(
                "Cross-encoder returned a score count that does not match the candidates."
            )
        scored = [
            replace(candidate, rerank_score=score)
            for candidate, score in zip(candidates, scores, strict=True)
        ]
        return sorted(
            scored,
            key=lambda item: (
                -(item.rerank_score if item.rerank_score is not None else float("-inf")),
                -item.rrf_score,
                item.evidence.chunk_id,
            ),
        )[:limit]

    async def _get_model(self) -> CrossEncoderModel:
        async with self._model_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._model_loader, self._model_name)
            return self._model
