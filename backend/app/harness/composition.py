"""Runtime composition for the only supported retrieval-backed chat path."""

from collections.abc import Callable

from backend.app.config import Settings
from backend.app.harness.chat_service import HarnessChatService
from backend.app.harness.nodes import (
    AnswerNode,
    DepartmentRule,
    FixedDagNodes,
    IntentNode,
    RetrieveNode,
    RewriteNode,
    RouteNode,
    VerifyNode,
)
from backend.app.harness.policy import PolicyHarness
from backend.app.llm.base import LLMClient, LLMTokenUsage
from backend.app.llm.fake import FakeLLM
from backend.app.llm.openai_compatible import OpenAICompatibleLLM
from backend.app.retrieval.bm25 import OpenSearchBM25
from backend.app.retrieval.dense import MilvusDenseIndex
from backend.app.retrieval.hybrid import HybridEvidenceRetriever
from backend.app.runtime.registry import RuntimeLLMClient, build_agent_runtime
from backend.app.storage.document_repository import DocumentStore
from backend.app.storage.trace_repository import TraceStore

_DEPARTMENT_RULES = [
    DepartmentRule("dept_tax", ("税", "增值税", "个税", "纳税", "发票")),
    DepartmentRule("dept_hr", ("社保", "就业", "劳动", "人才")),
    DepartmentRule("dept_market", ("营业执照", "市场监管", "企业登记")),
]


def build_chat_service(
    settings: Settings,
    *,
    document_store: DocumentStore,
    trace_store: TraceStore,
    usage_sink: Callable[[LLMTokenUsage], None] | None = None,
    llm_client: LLMClient | None = None,
) -> HarnessChatService:
    """Compose real Mongo/OpenSearch/Milvus gateways without an in-memory fallback."""

    llm: LLMClient
    if llm_client is not None:
        llm = llm_client
    elif settings.agent_runtime_backend != "legacy":
        llm = RuntimeLLMClient(build_agent_runtime(settings))
    elif settings.llm_mode == "remote":
        llm = OpenAICompatibleLLM(settings, usage_sink=usage_sink)
    else:
        llm = FakeLLM()
    retriever = HybridEvidenceRetriever.from_settings(
        settings,
        bm25=OpenSearchBM25(settings, index_name=settings.opensearch_index),
        dense=MilvusDenseIndex(settings, collection_name=settings.milvus_collection),
        canonical_store=document_store,
    )
    nodes = FixedDagNodes(
        intent=IntentNode(llm),
        rewrite=RewriteNode(llm),
        route=RouteNode(llm, rules=_DEPARTMENT_RULES),
        retrieve=RetrieveNode(retriever),
        answer=AnswerNode(llm),
        verify=VerifyNode(llm),
    )
    return HarnessChatService(
        PolicyHarness(nodes, trace_store=trace_store),
        resources=(llm, retriever),
    )
