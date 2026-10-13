"""Role-local composition for a department-agent process."""

from backend.app.agents.department_service import DepartmentAgentExecutor
from backend.app.config import Settings
from backend.app.harness.nodes import EvidenceRetriever
from backend.app.llm.base import LLMClient
from backend.app.llm.fake import FakeLLM
from backend.app.llm.openai_compatible import OpenAICompatibleLLM
from backend.app.retrieval.bm25 import OpenSearchBM25
from backend.app.retrieval.dense import MilvusDenseIndex
from backend.app.retrieval.hybrid import HybridEvidenceRetriever
from backend.app.runtime.registry import RuntimeLLMClient, build_agent_runtime
from backend.app.storage.document_repository import DocumentStore
from backend.app.storage.trace_repository import TraceStore

_CANONICAL_SCOPE_ALIASES = {
    # V1.0 public-policy corpus uses the stable canonical identifier below.
    # The V1.1 service identity remains the immutable logical tax department.
    "tax": "dept_tax",
}


def build_department_agent_executor(
    settings: Settings,
    *,
    document_store: DocumentStore,
    trace_store: TraceStore,
) -> DepartmentAgentExecutor:
    if settings.service_role != "department_agent" or not settings.dept_id:
        raise ValueError("Department executor may only be composed for department_agent role.")
    llm: LLMClient
    if settings.agent_runtime_backend != "legacy":
        llm = RuntimeLLMClient(build_agent_runtime(settings))
    elif settings.llm_mode == "remote":
        llm = OpenAICompatibleLLM(settings)
    else:
        llm = FakeLLM()
    retriever: EvidenceRetriever = HybridEvidenceRetriever.from_settings(
        settings,
        bm25=OpenSearchBM25(settings, index_name=settings.opensearch_index),
        dense=MilvusDenseIndex(settings, collection_name=settings.milvus_collection),
        canonical_store=document_store,
    )
    return DepartmentAgentExecutor(
        agent_id=settings.agent_id,
        dept_id=settings.dept_id,
        retriever=retriever,
        llm=llm,
        trace_store=trace_store,
        retrieval_department_ids=_retrieval_scope(settings.dept_id),
    )


def _retrieval_scope(dept_id: str) -> list[str]:
    canonical_alias = _CANONICAL_SCOPE_ALIASES.get(dept_id)
    return [dept_id, canonical_alias] if canonical_alias else [dept_id]
