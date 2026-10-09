import asyncio
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from opensearchpy import OpenSearch

from backend.app.config import Settings
from backend.app.domain.documents import DocumentVersionStatus
from backend.app.retrieval.rrf import RankedCandidate

POLICY_CHUNK_INDEX = "policy_chunks_bm25"
_ACTIVE_VERSION_STATUSES = (
    DocumentVersionStatus.ACTIVE.value,
    DocumentVersionStatus.ACTIVE_WITH_WARNING.value,
)


class BM25TokenizationError(RuntimeError):
    """The required Chinese tokenizer is unavailable for a real BM25 query/index."""


def tokenize_bm25(
    value: str, *, cutter: Callable[[str], Iterable[str]] | None = None
) -> str:
    """Normalize Chinese and whitespace-delimited text for the OpenSearch whitespace analyzer."""

    if not value.strip():
        return ""
    if cutter is None:
        try:
            import jieba  # type: ignore[import-untyped]
        except ModuleNotFoundError as error:
            raise BM25TokenizationError(
                "jieba is required for BM25 indexing and query normalization."
            ) from error
        cutter = jieba.cut
    return " ".join(token.strip().lower() for token in cutter(value) if token.strip())


@dataclass(frozen=True, slots=True)
class BM25ChunkRecord:
    chunk_id: str
    document_id: str
    version_id: str
    department_id: str
    title: str
    text: str
    active: bool = True
    version_status: DocumentVersionStatus = DocumentVersionStatus.ACTIVE
    bm25_text: str | None = None
    written_date: str | None = None

    def __post_init__(self) -> None:
        bm25_text = self.bm25_text or tokenize_bm25(f"{self.title}\n{self.text}")
        if not bm25_text.strip():
            raise ValueError("bm25_text must not be blank after tokenization.")
        if self.bm25_text != bm25_text:
            object.__setattr__(self, "bm25_text", bm25_text)


def policy_chunk_index_body() -> dict[str, Any]:
    return {
        "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "version_id": {"type": "keyword"},
                "department_id": {"type": "keyword"},
                "version_status": {"type": "keyword"},
                "active": {"type": "boolean"},
                "title": {"type": "text", "analyzer": "standard"},
                "text": {"type": "text", "index": False},
                "bm25_text": {"type": "text", "analyzer": "whitespace"},
                "written_date": {"type": "date", "format": "strict_date_optional_time||yyyy-MM-dd"},
            },
        },
    }


class OpenSearchBM25:
    """Real OpenSearch BM25 backend with lifecycle filtering and jieba-normalized queries."""

    def __init__(
        self,
        settings: Settings,
        *,
        index_name: str = POLICY_CHUNK_INDEX,
        tokenizer: Callable[[str], str] = tokenize_bm25,
        client_factory: Callable[[], OpenSearch] | None = None,
    ) -> None:
        self._index_name = index_name
        self._tokenizer = tokenizer
        self._client_factory = client_factory or (
            lambda: OpenSearch(hosts=[settings.opensearch_url], timeout=10)
        )
        self._client: OpenSearch | None = None

    def _get_client(self) -> OpenSearch:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        client = self._get_client()
        if not client.indices.exists(index=self._index_name):
            client.indices.create(index=self._index_name, body=policy_chunk_index_body())

    async def delete_index(self) -> None:
        """Delete an isolated integration-test index when it exists."""

        await asyncio.to_thread(self._delete_index)

    def _delete_index(self) -> None:
        client = self._get_client()
        if client.indices.exists(index=self._index_name):
            client.indices.delete(index=self._index_name)

    async def index_records(self, records: Sequence[BM25ChunkRecord]) -> None:
        await asyncio.to_thread(self._index_records, records)

    async def count_version_records(self, version_id: str) -> int:
        """Return the persisted count for an exact version-id consistency check."""

        return await asyncio.to_thread(self._count_version_records, version_id)

    def _index_records(self, records: Sequence[BM25ChunkRecord]) -> None:
        client = self._get_client()
        for record in records:
            client.index(
                index=self._index_name,
                id=record.chunk_id,
                body={
                    "chunk_id": record.chunk_id,
                    "document_id": record.document_id,
                    "version_id": record.version_id,
                    "department_id": record.department_id,
                    "version_status": record.version_status.value,
                    "active": record.active,
                    "title": record.title,
                    "text": record.text,
                    "bm25_text": record.bm25_text,
                    "written_date": record.written_date,
                },
                refresh=False,
            )
        if records:
            client.indices.refresh(index=self._index_name)

    def _count_version_records(self, version_id: str) -> int:
        response = self._get_client().count(
            index=self._index_name,
            body={"query": {"term": {"version_id": version_id}}},
        )
        return int(response["count"])

    async def search(
        self, query: str, *, department_ids: Sequence[str] = (), limit: int = 40
    ) -> list[RankedCandidate]:
        if not query.strip():
            return []
        if limit <= 0:
            raise ValueError("limit must be positive.")
        return await asyncio.to_thread(self._search, query, department_ids, limit)

    def _search(
        self, query: str, department_ids: Sequence[str], limit: int
    ) -> list[RankedCandidate]:
        normalized_query = self._tokenizer(query)
        if not normalized_query:
            return []
        filters: list[dict[str, Any]] = [
            {"term": {"active": True}},
            {"terms": {"version_status": list(_ACTIVE_VERSION_STATUSES)}},
        ]
        if department_ids:
            filters.append({"terms": {"department_id": list(department_ids)}})
        response = self._get_client().search(
            index=self._index_name,
            body={
                "size": limit,
                "query": {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": normalized_query,
                                    "fields": ["bm25_text^2", "title"],
                                    "type": "best_fields",
                                }
                            }
                        ],
                        "filter": filters,
                    }
                },
            },
        )
        hits = response["hits"]["hits"]
        return [
            RankedCandidate(
                chunk_id=str(hit["_source"]["chunk_id"]),
                document_id=str(hit["_source"]["document_id"]),
                version_id=str(hit["_source"]["version_id"]),
                rank=rank,
                raw_score=float(hit.get("_score") or 0.0),
            )
            for rank, hit in enumerate(hits, start=1)
        ]
