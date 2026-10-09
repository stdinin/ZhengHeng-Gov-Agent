from typing import Protocol

from backend.app.harness.state import AnswerStatus, HarnessResult, VerificationResult


class HarnessNodes(Protocol):
    async def intent(self, query: str) -> str: ...

    async def rewrite(self, query: str, intent: str) -> str: ...

    async def route(self, query: str) -> list[str]: ...

    async def retrieve(self, query: str, departments: list[str]) -> list[str]: ...

    async def answer(self, query: str, chunks: list[str]) -> str: ...

    async def verify(self, answer: str, chunks: list[str]) -> VerificationResult: ...


class HarnessRunner:
    """Run the only permitted DAG: Intent → Rewrite → Route → Retrieve → Answer → Verify."""

    def __init__(self, nodes: HarnessNodes) -> None:
        self._nodes = nodes

    async def run(self, query: str) -> HarnessResult:
        warnings: list[str] = []
        for attempt in range(1, 3):
            intent = await self._nodes.intent(query)
            rewritten_query = await self._nodes.rewrite(query, intent)
            departments = await self._nodes.route(rewritten_query)
            chunks = await self._nodes.retrieve(rewritten_query, departments)
            answer = await self._nodes.answer(rewritten_query, chunks)
            verification = await self._nodes.verify(answer, chunks)
            warnings.extend(verification.warnings)
            if verification.passed:
                return HarnessResult(
                    status=AnswerStatus.SUCCESS,
                    answer=answer,
                    attempts=attempt,
                    warnings=warnings,
                )
            if not verification.retryable:
                break
        return HarnessResult(
            status=AnswerStatus.ABSTAIN,
            answer="当前有效政策证据不足，暂不作答。",
            attempts=attempt,
            warnings=warnings,
        )
