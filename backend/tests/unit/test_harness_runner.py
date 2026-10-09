from dataclasses import dataclass, field

from backend.app.harness.runner import HarnessRunner
from backend.app.harness.state import AnswerStatus, VerificationResult


@dataclass
class ScriptedNodes:
    verification_results: list[VerificationResult]
    calls: list[str] = field(default_factory=list)

    async def intent(self, query: str) -> str:
        self.calls.append("Intent")
        return "POLICY_QA"

    async def rewrite(self, query: str, intent: str) -> str:
        self.calls.append("Rewrite")
        return query

    async def route(self, query: str) -> list[str]:
        self.calls.append("Route")
        return ["dept_tax"]

    async def retrieve(self, query: str, departments: list[str]) -> list[str]:
        self.calls.append("Retrieve")
        return ["chunk_active"]

    async def answer(self, query: str, chunks: list[str]) -> str:
        self.calls.append("Answer")
        return "依据现行政策的回答 [C1]"

    async def verify(self, answer: str, chunks: list[str]) -> VerificationResult:
        self.calls.append("Verify")
        return self.verification_results.pop(0)


async def test_harness_runs_the_fixed_dag_in_order() -> None:
    nodes = ScriptedNodes([VerificationResult(passed=True)])

    result = await HarnessRunner(nodes).run("小规模纳税人有什么优惠？")

    assert result.status is AnswerStatus.SUCCESS
    assert nodes.calls == ["Intent", "Rewrite", "Route", "Retrieve", "Answer", "Verify"]


async def test_verifier_failure_retries_once_then_abstains() -> None:
    nodes = ScriptedNodes(
        [
            VerificationResult(passed=False, retryable=True, warnings=["citation mismatch"]),
            VerificationResult(passed=False, retryable=True, warnings=["citation mismatch"]),
        ]
    )

    result = await HarnessRunner(nodes).run("小规模纳税人有什么优惠？")

    assert result.status is AnswerStatus.ABSTAIN
    assert result.attempts == 2
    assert nodes.calls.count("Verify") == 2
    assert nodes.calls == [
        "Intent",
        "Rewrite",
        "Route",
        "Retrieve",
        "Answer",
        "Verify",
        "Intent",
        "Rewrite",
        "Route",
        "Retrieve",
        "Answer",
        "Verify",
    ]
