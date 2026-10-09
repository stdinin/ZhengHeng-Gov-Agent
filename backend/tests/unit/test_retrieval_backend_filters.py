from typing import cast

import pytest
from opensearchpy import OpenSearch
from pymilvus import MilvusClient

from backend.app.config import Settings
from backend.app.retrieval.bm25 import OpenSearchBM25, tokenize_bm25
from backend.app.retrieval.dense import MilvusDenseIndex


class RecordingOpenSearch:
    def __init__(self) -> None:
        self.body: dict[str, object] | None = None

    def search(self, *, index: str, body: dict[str, object]) -> dict[str, object]:
        del index
        self.body = body
        return {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "chunk_id": "chunk-1",
                            "document_id": "doc-1",
                            "version_id": "ver-1",
                        },
                        "_score": 1.0,
                    }
                ]
            }
        }

    def close(self) -> None:
        return None


class RecordingMilvus:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def search(self, **kwargs: object) -> list[list[dict[str, object]]]:
        self.kwargs = kwargs
        return [
            [
                {
                    # PyMilvus 2.6 returns a VARCHAR primary key under its
                    # declared field name rather than a synthetic `id` key.
                    "chunk_id": "chunk-1",
                    "entity": {"document_id": "doc-1", "version_id": "ver-1"},
                    "distance": 1.0,
                }
            ]
        ]

    def close(self) -> None:
        return None


def test_bm25_tokenization_produces_the_whitespace_analyzer_payload() -> None:
    tokens = tokenize_bm25("小规模 纳税人 增值税", cutter=lambda _: ["小规模", "纳税人", "增值税"])

    assert tokens == "小规模 纳税人 增值税"


@pytest.mark.asyncio
async def test_opensearch_search_always_filters_to_active_fact_versions() -> None:
    client = RecordingOpenSearch()
    backend = OpenSearchBM25(
        Settings(),
        tokenizer=lambda _: "小规模 纳税人 增值税 优惠",
        client_factory=lambda: cast(OpenSearch, client),
    )

    results = await backend.search("小规模纳税人增值税优惠", department_ids=["dept_tax"])

    assert [item.chunk_id for item in results] == ["chunk-1"]
    assert client.body is not None
    query = cast(dict[str, object], client.body["query"])
    bool_query = cast(dict[str, object], query["bool"])
    filters = cast(list[dict[str, object]], bool_query["filter"])
    assert {"term": {"active": True}} in filters
    assert {"terms": {"version_status": ["ACTIVE", "ACTIVE_WITH_WARNING"]}} in filters
    assert {"terms": {"department_id": ["dept_tax"]}} in filters


@pytest.mark.asyncio
async def test_milvus_search_always_filters_to_active_fact_versions() -> None:
    client = RecordingMilvus()
    backend = MilvusDenseIndex(
        Settings(),
        embedding_dim=2,
        embedding_model="test-model",
        collection_name="policy_chunks_dense_test_filters",
        client_factory=lambda: cast(MilvusClient, client),
    )

    results = await backend.search([1.0, 0.0], department_ids=["dept_tax"])

    assert [item.chunk_id for item in results] == ["chunk-1"]
    assert client.kwargs is not None
    filter_expression = str(client.kwargs["filter"])
    assert "active == true" in filter_expression
    assert 'version_status in ["ACTIVE", "ACTIVE_WITH_WARNING"]' in filter_expression
    assert 'department_id in ["dept_tax"]' in filter_expression
