import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pymilvus import DataType, MilvusClient

from backend.app.config import Settings
from backend.app.domain.documents import DocumentVersionStatus
from backend.app.retrieval.rrf import RankedCandidate

POLICY_DENSE_COLLECTION = "policy_chunks_dense"
_ACTIVE_VERSION_STATUSES = (
    DocumentVersionStatus.ACTIVE.value,
    DocumentVersionStatus.ACTIVE_WITH_WARNING.value,
)


class DenseIndexError(RuntimeError):
    """The configured Milvus collection is incompatible with the embedding model."""


@dataclass(frozen=True, slots=True)
class DenseCollectionSpec:
    collection_name: str
    primary_key: str
    scalar_fields: tuple[str, ...]
    embedding_dim: int
    embedding_model: str
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class DenseVectorRecord:
    chunk_id: str
    document_id: str
    version_id: str
    department_id: str
    embedding: list[float]
    active: bool = True
    version_status: DocumentVersionStatus = DocumentVersionStatus.ACTIVE


def versioned_collection_name(
    base_collection_name: str, embedding_model: str, embedding_dim: int
) -> str:
    """Return a Milvus-safe collection version tied to one model and one dimension."""

    normalized_model = re.sub(r"[^a-z0-9]+", "_", embedding_model.lower()).strip("_")
    if not normalized_model:
        raise ValueError("embedding_model must contain at least one alphanumeric character.")
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive.")
    return f"{base_collection_name}__{normalized_model[:80]}__d{embedding_dim}"


def dense_collection_spec(
    *,
    embedding_dim: int,
    embedding_model: str,
    collection_name: str | None = None,
    base_collection_name: str = POLICY_DENSE_COLLECTION,
) -> DenseCollectionSpec:
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive.")
    if not embedding_model.strip():
        raise ValueError("embedding_model must not be blank.")
    resolved_name = collection_name or versioned_collection_name(
        base_collection_name, embedding_model, embedding_dim
    )
    return DenseCollectionSpec(
        collection_name=resolved_name,
        primary_key="chunk_id",
        scalar_fields=(
            "document_id",
            "version_id",
            "department_id",
            "version_status",
            "active",
        ),
        embedding_dim=embedding_dim,
        embedding_model=embedding_model,
        metadata={
            "zhengheng.embedding_model": embedding_model,
            "zhengheng.embedding_dimension": str(embedding_dim),
        },
    )


class MilvusDenseIndex:
    """Real Milvus vector index with versioned, model-bound collection metadata."""

    def __init__(
        self,
        settings: Settings,
        *,
        embedding_dim: int | None = None,
        embedding_model: str | None = None,
        collection_name: str | None = None,
        client_factory: Callable[[], MilvusClient] | None = None,
    ) -> None:
        self._spec = dense_collection_spec(
            embedding_dim=embedding_dim or settings.embedding_dimension,
            embedding_model=embedding_model or settings.embedding_model,
            collection_name=collection_name,
        )
        self._uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
        self._client_factory = client_factory or self._new_client

    @property
    def spec(self) -> DenseCollectionSpec:
        return self._spec

    def _new_client(self) -> MilvusClient:
        return MilvusClient(uri=self._uri)

    def _client(self) -> MilvusClient:
        return self._client_factory()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        client = self._client()
        try:
            if client.has_collection(self._spec.collection_name):
                self._assert_collection_metadata(client)
                return
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(
                field_name="chunk_id",
                datatype=DataType.VARCHAR,
                is_primary=True,
                max_length=128,
            )
            schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=128)
            schema.add_field(field_name="version_id", datatype=DataType.VARCHAR, max_length=128)
            schema.add_field(field_name="department_id", datatype=DataType.VARCHAR, max_length=128)
            schema.add_field(field_name="version_status", datatype=DataType.VARCHAR, max_length=32)
            schema.add_field(field_name="active", datatype=DataType.BOOL)
            schema.add_field(
                field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=self._spec.embedding_dim
            )
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE"
            )
            client.create_collection(
                collection_name=self._spec.collection_name,
                schema=schema,
                index_params=index_params,
                properties=dict(self._spec.metadata),
            )
        finally:
            client.close()

    def _assert_collection_metadata(self, client: MilvusClient) -> None:
        description = client.describe_collection(self._spec.collection_name)
        raw_properties = description.get("properties", {})
        properties = (
            {str(key): str(value) for key, value in raw_properties.items()}
            if isinstance(raw_properties, dict)
            else {}
        )
        mismatched = {
            key: (properties.get(key), expected)
            for key, expected in self._spec.metadata.items()
            if properties.get(key) != expected
        }
        if mismatched:
            raise DenseIndexError(
                "Existing Milvus collection metadata does not match the configured embedding "
                f"model/dimension: {mismatched}"
            )

    async def drop_collection(self) -> None:
        """Remove an isolated test collection; callers must scope its name safely."""

        await asyncio.to_thread(self._drop_collection)

    def _drop_collection(self) -> None:
        client = self._client()
        try:
            if client.has_collection(self._spec.collection_name):
                client.drop_collection(self._spec.collection_name)
        finally:
            client.close()

    async def upsert(self, records: list[DenseVectorRecord]) -> None:
        for record in records:
            if len(record.embedding) != self._spec.embedding_dim:
                raise ValueError(
                    "Embedding dimension does not match the configured Milvus collection."
                )
        await asyncio.to_thread(self._upsert, records)

    async def count_version_records(self, version_id: str) -> int:
        """Return the persisted count for an exact version-id consistency check."""

        return await asyncio.to_thread(self._count_version_records, version_id)

    def _upsert(self, records: list[DenseVectorRecord]) -> None:
        if not records:
            return
        client = self._client()
        try:
            client.upsert(
                collection_name=self._spec.collection_name,
                data=[
                    {
                        "chunk_id": record.chunk_id,
                        "document_id": record.document_id,
                        "version_id": record.version_id,
                        "department_id": record.department_id,
                        "version_status": record.version_status.value,
                        "active": record.active,
                        "embedding": record.embedding,
                    }
                    for record in records
                ],
            )
            # Consistency checks immediately query this collection.  Flush the
            # real write before reporting an index operation as complete.
            client.flush(self._spec.collection_name)
        finally:
            client.close()

    def _count_version_records(self, version_id: str) -> int:
        client = self._client()
        try:
            escaped = self._escape_filter_value(version_id)
            records = client.query(
                collection_name=self._spec.collection_name,
                filter=f'version_id == "{escaped}"',
                output_fields=[self._spec.primary_key],
                limit=16_384,
            )
            return len(records)
        finally:
            client.close()

    async def search(
        self, vector: list[float], *, department_ids: list[str] | None = None, limit: int = 40
    ) -> list[RankedCandidate]:
        if len(vector) != self._spec.embedding_dim:
            raise ValueError(
                "Query embedding dimension does not match the configured Milvus collection."
            )
        if limit <= 0:
            raise ValueError("limit must be positive.")
        return await asyncio.to_thread(self._search, vector, department_ids or [], limit)

    def _search(
        self, vector: list[float], department_ids: list[str], limit: int
    ) -> list[RankedCandidate]:
        client = self._client()
        try:
            filter_parts = [
                "active == true",
                "version_status in [\"ACTIVE\", \"ACTIVE_WITH_WARNING\"]",
            ]
            if department_ids:
                escaped = ", ".join(
                    f'"{self._escape_filter_value(item)}"' for item in department_ids
                )
                filter_parts.append(f"department_id in [{escaped}]")
            response: list[list[dict[str, Any]]] = client.search(
                collection_name=self._spec.collection_name,
                data=[vector],
                filter=" and ".join(filter_parts),
                limit=limit,
                output_fields=["document_id", "version_id"],
            )
            candidates: list[RankedCandidate] = []
            for rank, hit in enumerate(response[0], start=1):
                # PyMilvus returns VARCHAR primary keys under their declared
                # field name (e.g. `chunk_id`), whereas older response shapes
                # exposed a synthetic `id` key.
                chunk_id = hit.get(self._spec.primary_key, hit.get("id"))
                if chunk_id is None:
                    raise DenseIndexError(
                        "Milvus search hit did not include the configured primary key "
                        f"{self._spec.primary_key!r}."
                    )
                candidates.append(
                    RankedCandidate(
                        chunk_id=str(chunk_id),
                        document_id=str(hit["entity"]["document_id"]),
                        version_id=str(hit["entity"]["version_id"]),
                        rank=rank,
                        raw_score=float(hit["distance"]),
                    )
                )
            return candidates
        finally:
            client.close()

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
