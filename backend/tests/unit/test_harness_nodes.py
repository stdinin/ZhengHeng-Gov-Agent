from dataclasses import dataclass

from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.citations import Evidence, render_cited_answer
from backend.app.harness.nodes import (
    AnswerNode,
    DepartmentRule,
    IntentNode,
    RetrieveNode,
    RewriteNode,
    RouteNode,
    VerifyNode,
)
from backend.app.harness.state import AnswerClaim, RouteDecision
from backend.app.llm.fake import FakeLLM


class StaticEvidenceRetriever:
    async def retrieve(
        self, *, queries: list[str], department_ids: list[str], limit: int
    ) -> list[Evidence]:
        assert queries == ["增值税有哪些优惠？", "增值税优惠"]
        assert department_ids == ["dept_tax"]
        assert limit == 8
        return [
            Evidence(
                chunk_id="chunk_tax_1",
                document_id="doc_tax_1",
                version_id="ver_tax_1",
                title="增值税优惠",
                department="税务",
                status=DocumentVersionStatus.ACTIVE,
                text="符合条件的纳税人可以享受优惠。",
            )
        ]


@dataclass(frozen=True)
class TraceableRetrievalResult:
    evidence: list[Evidence]
    trace: object


class TraceableEvidenceRetriever:
    async def retrieve(
        self, *, queries: list[str], department_ids: list[str], limit: int
    ) -> list[Evidence]:
        raise AssertionError("RetrieveNode should use retrieve_with_trace when it is available.")

    async def retrieve_with_trace(
        self, *, queries: list[str], department_ids: list[str], limit: int
    ) -> TraceableRetrievalResult:
        return TraceableRetrievalResult(
            evidence=[
                Evidence(
                    chunk_id="chunk_trace_1",
                    document_id="doc_trace_1",
                    version_id="ver_trace_1",
                    title="优惠政策",
                    department="税务",
                    status=DocumentVersionStatus.ACTIVE,
                    text="符合条件的主体享受优惠。",
                )
            ],
            trace={"bm25_candidate_count": 1, "reranker_skipped": False},
        )


async def test_nodes_use_schema_validated_candidates_and_bound_evidence() -> None:
    llm = FakeLLM(
        structured_fixtures={
            "intent": {"intent": "POLICY_QUERY", "entities": {}, "confidence": 0.95},
            "rewrite": {"queries": ["增值税优惠"]},
            "route": {"routes": [{"department_id": "dept_tax", "score": 0.95}]},
            "answer": {
                "answer": "符合条件的纳税人可以享受优惠。",
                "claims": [
                    {"text": "符合条件的纳税人可以享受优惠。", "citation_ids": ["C1"]}
                ],
            },
        }
    )
    intent = await IntentNode(llm).run("增值税有哪些优惠？")
    rewrite = await RewriteNode(llm).run("增值税有哪些优惠？", intent)
    route = await RouteNode(
        llm,
        rules=[DepartmentRule("dept_tax", ("增值税", "纳税"))],
    ).run(rewrite.queries, intent)
    evidence = await RetrieveNode(StaticEvidenceRetriever()).run(rewrite.queries, route)
    answer = await AnswerNode(llm).run("增值税有哪些优惠？", evidence)

    assert intent.intent == "POLICY_QUERY"
    assert rewrite.queries == ["增值税有哪些优惠？", "增值税优惠"]
    assert route.department_ids == ["dept_tax"]
    assert evidence[0].chunk_id == "chunk_tax_1"
    assert answer.claims[0].citation_ids == ["C1"]


async def test_nodes_fallback_without_an_llm_fixture_never_invents_a_policy_answer() -> None:
    llm = FakeLLM()

    intent = await IntentNode(llm).run("我想咨询政策")
    rewrite = await RewriteNode(llm).run("我想咨询政策", intent)
    answer = await AnswerNode(llm).run("我想咨询政策", [])

    assert intent.used_fallback is True
    assert rewrite.queries == ["我想咨询政策"]
    assert answer.content == "当前有效政策证据不足，暂不作答。"
    assert answer.claims == []


async def test_verify_node_rejects_a_claim_that_the_semantic_check_does_not_support() -> None:
    evidence = [
        Evidence(
            chunk_id="chunk_tax_1",
            document_id="doc_tax_1",
            version_id="ver_tax_1",
            title="增值税优惠",
            department="税务",
            status=DocumentVersionStatus.ACTIVE,
            text="符合条件的纳税人可以享受优惠。",
        )
    ]
    claims = [AnswerClaim(text="所有纳税人都可以享受优惠。", citation_ids=["C1"])]
    answer, citations = render_cited_answer(claims[0].text, evidence, claims=claims)
    llm = FakeLLM(
        structured_fixtures={
            "verify_claim": {
                "supported": False,
                "support_score": 0.2,
                "contradiction": True,
                "reason": "原文只限定符合条件的纳税人。",
            }
        }
    )

    verification = await VerifyNode(llm).run(
        answer=answer,
        citations=citations,
        evidence=evidence,
        claims=claims,
    )

    assert verification.passed is False
    assert verification.retryable is True
    assert any("contradiction" in warning.lower() for warning in verification.warnings)


async def test_retrieve_node_preserves_real_backend_stage_metadata_for_trace() -> None:
    result = await RetrieveNode(TraceableEvidenceRetriever()).run_with_trace(
        queries=["增值税优惠"],
        route=RouteDecision.model_validate(
            {"routes": [{"department_id": "dept_tax", "score": 1.0}]}
        ),
    )

    assert [item.chunk_id for item in result[0]] == ["chunk_trace_1"]
    assert result[1] == {"bm25_candidate_count": 1, "reranker_skipped": False}


async def test_answer_node_requires_a_temporal_warning_for_active_warning_evidence() -> None:
    class CapturingLLM:
        system_prompt = ""

        async def structured(self, **kwargs: object) -> object:
            self.system_prompt = str(kwargs["system"])
            schema = kwargs["schema"]
            return schema.model_validate(
                {
                    "answer": "该文件存在部分失效/时效性警告。",
                    "claims": [
                        {
                            "text": "该文件存在部分失效/时效性警告。",
                            "citation_ids": ["C1"],
                        }
                    ],
                }
            )

    llm = CapturingLLM()
    await AnswerNode(llm).run(
        "有哪些优惠？",
        [
            Evidence(
                chunk_id="chunk_warning",
                document_id="doc_warning",
                version_id="ver_warning",
                title="部分有效文件",
                department="税务",
                status=DocumentVersionStatus.ACTIVE_WITH_WARNING,
                text="本文件仅部分条款仍有效。",
            )
        ],
    )

    assert "部分失效/时效性警告" in llm.system_prompt
