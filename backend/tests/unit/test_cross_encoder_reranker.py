from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.citations import Evidence
from backend.app.retrieval import reranker as reranker_module
from backend.app.retrieval.reranker import (
    CrossEncoderReranker,
    ScoredEvidence,
    _load_sentence_transformers_cross_encoder,
)


@dataclass
class RecordingCrossEncoder:
    pairs: list[tuple[str, str]] = field(default_factory=list)

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.pairs = pairs
        return [0.1, 0.9]


@dataclass
class BatchRecordingCrossEncoder:
    batch_sizes: list[int] = field(default_factory=list)

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.batch_sizes.append(len(pairs))
        return [float(pair[1].split()[-1]) for pair in pairs]


def _candidate(chunk_id: str, rrf_score: float) -> ScoredEvidence:
    return ScoredEvidence(
        evidence=Evidence(
            chunk_id=chunk_id,
            document_id=f"doc-{chunk_id}",
            version_id=f"ver-{chunk_id}",
            title=f"政策 {chunk_id}",
            department="tax",
            status=DocumentVersionStatus.ACTIVE,
            text=f"政策正文 {chunk_id}",
        ),
        rrf_score=rrf_score,
    )


def test_windows_loader_avoids_transformers_meta_device_native_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_factory(model_name: str, **kwargs: object) -> RecordingCrossEncoder:
        captured.update(model_name=model_name, **kwargs)
        return RecordingCrossEncoder()

    monkeypatch.setattr(reranker_module.sys, "platform", "win32")
    monkeypatch.setattr(
        reranker_module.importlib,
        "import_module",
        lambda name: SimpleNamespace(CrossEncoder=fake_factory),
    )

    _load_sentence_transformers_cross_encoder("BAAI/bge-reranker-v2-m3")

    assert captured == {
        "model_name": "BAAI/bge-reranker-v2-m3",
        "automodel_args": {
            "low_cpu_mem_usage": False,
            "dtype": "float32",
        },
    }


@pytest.mark.asyncio
async def test_cross_encoder_adapter_loads_the_configured_model_and_orders_real_scores() -> None:
    loaded_models: list[str] = []
    encoder = RecordingCrossEncoder()
    reranker = CrossEncoderReranker(
        model_name="BAAI/bge-reranker-v2-m3",
        model_loader=lambda model_name: (loaded_models.append(model_name) or encoder),
    )

    reranked = await reranker.rerank(
        "小规模纳税人增值税优惠",
        [_candidate("first", 0.8), _candidate("second", 0.1)],
        limit=2,
    )

    assert loaded_models == ["BAAI/bge-reranker-v2-m3"]
    assert encoder.pairs == [
        ("小规模纳税人增值税优惠", "政策 first\n政策正文 first"),
        ("小规模纳税人增值税优惠", "政策 second\n政策正文 second"),
    ]
    assert [item.evidence.chunk_id for item in reranked] == ["second", "first"]
    assert [item.rerank_score for item in reranked] == [0.9, 0.1]


@pytest.mark.asyncio
async def test_cross_encoder_scores_all_candidates_in_bounded_batches() -> None:
    encoder = BatchRecordingCrossEncoder()
    reranker = CrossEncoderReranker(
        model_name="BAAI/bge-reranker-v2-m3",
        model_loader=lambda model_name: encoder,
        prediction_batch_size=3,
    )

    reranked = await reranker.rerank(
        "税收政策",
        [_candidate(str(index), 0.1) for index in range(7)],
        limit=7,
    )

    assert encoder.batch_sizes == [3, 3, 1]
    assert [item.evidence.chunk_id for item in reranked] == ["6", "5", "4", "3", "2", "1", "0"]
