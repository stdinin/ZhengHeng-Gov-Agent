"""Composition of the opt-in global multi-agent orchestration profile."""

from backend.app.agents.aggregator import MultiAgentAggregator
from backend.app.agents.chat_service import MultiAgentChatService
from backend.app.agents.client import HTTPDepartmentAgentClient
from backend.app.agents.memory import RootMemoryCoordinator
from backend.app.agents.models import MultiAgentRouteDecision
from backend.app.agents.orchestrator import (
    DepartmentDispatcher,
    GlobalOrchestrator,
    RegistryRouteNode,
)
from backend.app.agents.registry import department_agent_registry_from_settings
from backend.app.config import Settings
from backend.app.harness.nodes import DepartmentRule, IntentNode, RewriteNode, RouteNode
from backend.app.harness.state import IntentDecision, RewriteDecision
from backend.app.llm.base import LLMClient
from backend.app.llm.fake import FakeLLM
from backend.app.llm.openai_compatible import OpenAICompatibleLLM
from backend.app.memory.context import MemoryContextService
from backend.app.memory.repository import MemoryRepository
from backend.app.memory.working import RedisWorkingMemory
from backend.app.runtime.registry import RuntimeLLMClient, build_agent_runtime
from backend.app.storage.trace_repository import TraceStore

_MULTI_AGENT_RULES = [
    DepartmentRule("tax", ("税", "增值税", "个税", "纳税", "发票")),
    DepartmentRule("hrss", ("社保", "社会保险", "就业", "劳动", "人才")),
    DepartmentRule("housing", ("住房", "公积金", "房屋", "租赁")),
]


def build_multi_agent_chat_service(
    settings: Settings, *, trace_store: TraceStore, memory_repository: MemoryRepository
) -> MultiAgentChatService:
    registry = department_agent_registry_from_settings(settings)
    llm: LLMClient
    if settings.agent_runtime_backend != "legacy":
        llm = RuntimeLLMClient(build_agent_runtime(settings))
    elif settings.llm_mode == "remote":
        llm = OpenAICompatibleLLM(settings)
    else:
        llm = FakeLLM()
    client = HTTPDepartmentAgentClient(service_token=settings.internal_service_token or "")
    orchestrator = GlobalOrchestrator(
        nodes=_MultiAgentSemanticNodes(
            intent=IntentNode(llm),
            rewrite=RewriteNode(llm),
            route=RegistryRouteNode(
                route_node=RouteNode(llm, rules=_MULTI_AGENT_RULES),
                registry=registry,
                max_departments=settings.multi_agent_max_departments,
            ),
        ),
        registry=registry,
        dispatcher=DepartmentDispatcher(
            client=client,
            max_parallel=settings.orchestrator_max_parallel,
        ),
        aggregator=MultiAgentAggregator(llm),
        trace_store=trace_store,
        max_departments=settings.multi_agent_max_departments,
    )
    working_memory = RedisWorkingMemory(settings)
    memory = RootMemoryCoordinator(
        context_service=MemoryContextService(
            repository=memory_repository,
            working_memory=working_memory,
        ),
        repository=memory_repository,
        token_budget=settings.memory_token_budget,
    )
    return MultiAgentChatService(
        orchestrator,
        resources=(llm, client, working_memory),
        memory=memory,
    )


class _MultiAgentSemanticNodes:
    def __init__(
        self, *, intent: IntentNode, rewrite: RewriteNode, route: RegistryRouteNode
    ) -> None:
        self._intent = intent
        self._rewrite = rewrite
        self._route = route

    async def intent(self, query: str) -> IntentDecision:
        return await self._intent.run(query)

    async def rewrite(self, query: str, intent: IntentDecision) -> RewriteDecision:
        return await self._rewrite.run(query, intent)

    async def route(
        self, queries: list[str], intent: IntentDecision
    ) -> MultiAgentRouteDecision:
        return await self._route.route(queries, intent)
