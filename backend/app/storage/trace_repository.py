from dataclasses import asdict
from typing import Any, Protocol

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from backend.app.config import Settings
from backend.app.harness.state import AnswerStatus
from backend.app.observability.tracing import TraceNode, TraceRecord


class TraceStore(Protocol):
    async def save(self, trace: TraceRecord) -> None: ...

    async def get(self, trace_id: str) -> TraceRecord | None: ...

    async def list_for_user(
        self, user_id: str, *, session_id: str | None = None, limit: int = 50
    ) -> list[TraceRecord]: ...

    async def list_recent(self, *, limit: int = 100) -> list[TraceRecord]: ...


class MongoTraceStore:
    """Real MongoDB persistence for append-only execution traces."""

    def __init__(self, settings: Settings) -> None:
        self._client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongo_uri)
        self._collection: AsyncCollection[dict[str, Any]] = self._client[settings.mongo_db][
            "traces"
        ]

    async def close(self) -> None:
        """Release background Mongo monitoring tasks for scripts and test runs."""

        client = getattr(self, "_client", None)
        if client is None:
            return
        await client.close()
        for attribute in ("_collection", "_client"):
            if hasattr(self, attribute):
                delattr(self, attribute)

    async def save(self, trace: TraceRecord) -> None:
        document = asdict(trace)
        document["_id"] = document.pop("id")
        await self._collection.replace_one({"_id": document["_id"]}, document, upsert=True)

    async def get(self, trace_id: str) -> TraceRecord | None:
        document = await self._collection.find_one({"_id": trace_id})
        if document is None:
            return None
        return self._from_document(document)

    async def list_for_user(
        self, user_id: str, *, session_id: str | None = None, limit: int = 50
    ) -> list[TraceRecord]:
        query: dict[str, Any] = {"user_id": user_id}
        if session_id is not None:
            query["session_id"] = session_id
        cursor = self._collection.find(query).sort("created_at", -1).limit(limit)
        return [self._from_document(document) async for document in cursor]

    async def list_recent(self, *, limit: int = 100) -> list[TraceRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("Recent trace limit must be between 1 and 500.")
        cursor = self._collection.find({}).sort("created_at", -1).limit(limit)
        return [self._from_document(document) async for document in cursor]

    @staticmethod
    def _from_document(document: dict[str, Any]) -> TraceRecord:
        raw_intent = document.get("intent")
        raw_verification = document.get("verification")
        raw_retrieval_metadata = document.get("retrieval_metadata")
        raw_timings = document.get("timings_ms")
        raw_route_decision = document.get("route_decision")
        raw_final_verification = document.get("final_verification")
        return TraceRecord(
            id=str(document["_id"]),
            user_id=document.get("user_id"),
            session_id=str(document["session_id"]),
            query=str(document["query"]),
            nodes=[TraceNode(**node) for node in document.get("nodes", [])],
            status=AnswerStatus(document["status"]),
            answer=str(document["answer"]),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
            normalized_query=(
                str(document["normalized_query"])
                if document.get("normalized_query") is not None
                else None
            ),
            intent=dict(raw_intent) if isinstance(raw_intent, dict) else None,
            rewritten_queries=_string_list(document.get("rewritten_queries")),
            department_routes=_mapping_list(document.get("department_routes")),
            memory_context=_string_list(document.get("memory_context")),
            matched_strategies=_string_list(document.get("matched_strategies")),
            retrieval_hits=_string_list(document.get("retrieval_hits")),
            retrieval_metadata=(
                dict(raw_retrieval_metadata)
                if isinstance(raw_retrieval_metadata, dict)
                else {}
            ),
            citations=_mapping_list(document.get("citations")),
            verification=(dict(raw_verification) if isinstance(raw_verification, dict) else None),
            retry_count=int(document.get("retry_count", 0)),
            errors=_string_list(document.get("errors")),
            timings_ms=(
                {str(key): float(value) for key, value in raw_timings.items()}
                if isinstance(raw_timings, dict)
                else {}
            ),
            parent_trace_id=(
                str(document["parent_trace_id"])
                if document.get("parent_trace_id") is not None
                else None
            ),
            trace_kind=str(document.get("trace_kind", "root")),
            execution_mode=str(document.get("execution_mode", "single_agent")),
            agent_id=str(document["agent_id"]) if document.get("agent_id") is not None else None,
            dept_id=str(document["dept_id"]) if document.get("dept_id") is not None else None,
            child_trace_ids=_string_list(document.get("child_trace_ids")),
            aggregation=(
                dict(document["aggregation"])
                if isinstance(document.get("aggregation"), dict)
                else {}
            ),
            partial=bool(document.get("partial", False)),
            failed_departments=_mapping_list(document.get("failed_departments")),
            runtime_fallbacks=_mapping_list(document.get("runtime_fallbacks")),
            route_decision=(
                dict(raw_route_decision) if isinstance(raw_route_decision, dict) else None
            ),
            selected_departments=_string_list(document.get("selected_departments")),
            final_verification=(
                dict(raw_final_verification)
                if isinstance(raw_final_verification, dict)
                else None
            ),
        )


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
