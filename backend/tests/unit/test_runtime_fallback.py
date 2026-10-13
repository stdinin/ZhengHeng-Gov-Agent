import pytest
from pydantic import BaseModel


class RewritePayload(BaseModel):
    queries: list[str]


@pytest.mark.asyncio
async def test_fallback_runtime_uses_secondary_after_primary_timeout() -> None:
    from backend.app.runtime.base import RuntimeMessage, RuntimeNode
    from backend.app.runtime.fake import FakeRuntime
    from backend.app.runtime.registry import FallbackAgentRuntime

    primary = FakeRuntime(errors={RuntimeNode.REWRITE: TimeoutError("pi timeout")})
    fallback = FakeRuntime(
        fixtures={RuntimeNode.REWRITE: {"queries": ["原 query"]}}, backend_name="fake"
    )
    runtime = FallbackAgentRuntime(primary=primary, fallback=fallback)

    result = await runtime.invoke(
        node=RuntimeNode.REWRITE,
        agent_id="orchestrator",
        dept_id=None,
        trace_id="trace-1",
        system_prompt="rewrite",
        messages=[RuntimeMessage(role="user", content="原 query")],
        response_model=RewritePayload,
        timeout_ms=50,
    )

    assert result.output.queries == ["原 query"]
    assert result.backend_used == "fake"
    assert result.fallback_reason == "TimeoutError"


@pytest.mark.asyncio
async def test_exhausted_runtime_fails_closed_for_answer_node() -> None:
    from backend.app.domain.documents import DocumentVersionStatus
    from backend.app.harness.citations import Evidence
    from backend.app.harness.nodes import AnswerNode
    from backend.app.runtime.fake import FakeRuntime
    from backend.app.runtime.registry import RuntimeLLMClient

    runtime = FakeRuntime(errors={})
    answer = await AnswerNode(RuntimeLLMClient(runtime)).run(
        "税收优惠",
        [
            Evidence(
                chunk_id="chunk-1",
                document_id="doc-1",
                version_id="ver-1",
                title="政策",
                department="dept_tax",
                status=DocumentVersionStatus.ACTIVE,
                text="政策原文",
            )
        ],
    )

    assert answer.content == "当前有效政策证据不足，暂不作答。"
