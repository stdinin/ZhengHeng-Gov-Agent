from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.citations import Citation, CitationCheck, Evidence
from backend.app.harness.policy import AnswerDraft, PolicyHarness
from backend.app.harness.state import (
    AnswerClaim,
    AnswerStatus,
    IntentDecision,
    IntentKind,
    RewriteDecision,
    RouteDecision,
    VerificationResult,
)
from backend.app.observability.tracing import TraceRecord


@dataclass
class StaticPolicyNodes:
    evidence: list[Evidence]

    async def intent(self, query: str) -> IntentDecision:
        return IntentDecision(intent=IntentKind.POLICY_QUERY, confidence=1.0)

    async def rewrite(self, query: str, intent: IntentDecision) -> RewriteDecision:
        return RewriteDecision(queries=[query])

    async def route(self, queries: list[str], intent: IntentDecision) -> RouteDecision:
        return RouteDecision.model_validate(
            {"routes": [{"department_id": "dept_tax", "score": 1.0}]}
        )

    async def retrieve(self, queries: list[str], route: RouteDecision) -> list[Evidence]:
        return self.evidence

    async def answer(self, query: str, evidence: list[Evidence]) -> AnswerDraft:
        return AnswerDraft(
            content="符合条件的主体可享受优惠。",
            claims=[AnswerClaim(text="符合条件的主体可享受优惠。", citation_ids=["C1"])],
        )

    async def verify(
        self,
        *,
        answer: str,
        citations: list[Citation],
        evidence: list[Evidence],
        claims: list[AnswerClaim],
    ) -> VerificationResult:
        return CitationCheck().validate(answer, citations, evidence, claims=claims)


@dataclass
class RecordingTraceStore:
    traces: list[TraceRecord] = field(default_factory=list)

    async def save(self, trace: TraceRecord) -> None:
        self.traces.append(trace)


@dataclass
class SemanticallyRejectedNodes(StaticPolicyNodes):
    verify_calls: int = 0

    async def verify(
        self,
        *,
        answer: str,
        citations: list[Citation],
        evidence: list[Evidence],
        claims: list[AnswerClaim],
    ) -> VerificationResult:
        del answer, citations, evidence, claims
        self.verify_calls += 1
        return VerificationResult(
            passed=False,
            retryable=False,
            warnings=["Semantic contradiction: cited evidence narrows the claim."],
        )


@dataclass
class TraceAwareStaticPolicyNodes(StaticPolicyNodes):
    async def retrieve_with_trace(
        self, queries: list[str], route: RouteDecision
    ) -> tuple[list[Evidence], dict[str, object]]:
        del queries, route
        return self.evidence, {"bm25_candidate_count": 4, "reranker_skipped": False}


async def test_policy_harness_generates_citations_and_persists_full_dag_trace() -> None:
    nodes = StaticPolicyNodes(
        [
            Evidence(
                chunk_id="chunk_1",
                document_id="doc_1",
                version_id="ver_1",
                title="优惠政策",
                department="税务",
                status=DocumentVersionStatus.ACTIVE,
                text="符合条件的主体享受优惠。",
            )
        ]
    )
    trace_store = RecordingTraceStore()

    result = await PolicyHarness(nodes, trace_store=trace_store).run(
        query="有什么优惠？",
        trace_id="trace_policy_1",
        session_id="session_1",
        user_id="user_1",
        now=datetime.now(UTC),
    )

    assert result.status is AnswerStatus.SUCCESS
    assert result.citations[0].id == "C1"
    assert [node.node for node in trace_store.traces[0].nodes] == [
        "Intent",
        "Rewrite",
        "Route",
        "Retrieve",
        "Answer",
        "Verify",
    ]
    assert trace_store.traces[0].normalized_query == "有什么优惠？"
    assert trace_store.traces[0].citations[0]["id"] == "C1"
    assert trace_store.traces[0].verification == {
        "passed": True,
        "retryable": True,
        "warnings": [],
    }


async def test_policy_harness_abstains_when_retrieval_has_no_active_evidence() -> None:
    trace_store = RecordingTraceStore()

    result = await PolicyHarness(StaticPolicyNodes([]), trace_store=trace_store).run(
        query="有什么优惠？",
        trace_id="trace_policy_2",
        session_id="session_1",
        user_id="user_1",
        now=datetime.now(UTC),
    )

    assert result.status is AnswerStatus.ABSTAIN
    assert result.citations == []
    assert trace_store.traces[0].status is AnswerStatus.ABSTAIN


async def test_policy_harness_uses_the_verify_node_before_returning_success() -> None:
    nodes = SemanticallyRejectedNodes(
        [
            Evidence(
                chunk_id="chunk_1",
                document_id="doc_1",
                version_id="ver_1",
                title="优惠政策",
                department="税务",
                status=DocumentVersionStatus.ACTIVE,
                text="符合条件的主体享受优惠。",
            )
        ]
    )
    trace_store = RecordingTraceStore()

    result = await PolicyHarness(nodes, trace_store=trace_store).run(
        query="有什么优惠？",
        trace_id="trace_policy_verify",
        session_id="session_1",
        user_id="user_1",
        now=datetime.now(UTC),
    )

    assert result.status is AnswerStatus.ABSTAIN
    assert nodes.verify_calls == 1
    assert "Semantic contradiction" in result.warnings[0]


async def test_policy_harness_persists_retrieval_stage_metadata_in_trace() -> None:
    nodes = TraceAwareStaticPolicyNodes(
        [
            Evidence(
                chunk_id="chunk_1",
                document_id="doc_1",
                version_id="ver_1",
                title="优惠政策",
                department="税务",
                status=DocumentVersionStatus.ACTIVE,
                text="符合条件的主体享受优惠。",
            )
        ]
    )
    trace_store = RecordingTraceStore()

    await PolicyHarness(nodes, trace_store=trace_store).run(
        query="有什么优惠？",
        trace_id="trace_policy_retrieval",
        session_id="session_1",
        user_id="user_1",
        now=datetime.now(UTC),
    )

    assert trace_store.traces[0].retrieval_metadata == {
        "bm25_candidate_count": 4,
        "reranker_skipped": False,
    }
