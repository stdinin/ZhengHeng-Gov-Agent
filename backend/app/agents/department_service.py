"""Single-department execution with immutable scope and child-trace persistence."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime
from inspect import isawaitable
from typing import Any, Protocol, cast
from uuid import uuid4

from backend.app.agents.models import (
    DepartmentAgentResult,
    DepartmentCitation,
    DepartmentExecutionRequest,
    DepartmentExecutionStatus,
)
from backend.app.harness.citations import Citation, Evidence, render_cited_answer
from backend.app.harness.nodes import (
    AnswerNode,
    EvidenceRetriever,
    TraceableEvidenceRetriever,
    VerifyNode,
)
from backend.app.harness.policy import AnswerDraft
from backend.app.harness.state import AnswerStatus
from backend.app.llm.base import LLMClient
from backend.app.observability.tracing import TraceRecorder
from backend.app.runtime.context import RuntimeInvocationAudit, runtime_request_scope
from backend.app.storage.trace_repository import TraceStore


class DepartmentRetriever(EvidenceRetriever, Protocol):
    pass


class DepartmentAgentService(Protocol):
    async def execute(
        self, request: DepartmentExecutionRequest, *, now: datetime
    ) -> DepartmentAgentResult: ...


class DepartmentAgentExecutor:
    """Runs only the local retrieve-answer-verify chain for a fixed department."""

    def __init__(
        self,
        *,
        agent_id: str,
        dept_id: str,
        retriever: DepartmentRetriever,
        llm: LLMClient,
        trace_store: TraceStore,
        retrieval_department_ids: list[str] | None = None,
    ) -> None:
        if not agent_id or not dept_id:
            raise ValueError("Department service requires immutable AGENT_ID and DEPT_ID.")
        self._agent_id = agent_id
        self._dept_id = dept_id
        self._retrieval_department_ids = list(
            dict.fromkeys(retrieval_department_ids or [dept_id])
        )
        self._retriever = retriever
        self._answer_node = AnswerNode(llm)
        self._verify_node = VerifyNode(llm)
        self._llm = llm
        self._trace_store = trace_store

    async def close(self) -> None:
        """Release only the executor-owned semantic and retrieval clients."""

        seen: set[int] = set()
        for resource in (self._llm, self._retriever):
            if id(resource) in seen:
                continue
            seen.add(id(resource))
            close = getattr(resource, "close", None)
            if callable(close):
                outcome = close()
                if isawaitable(outcome):
                    await outcome

    async def execute(
        self, request: DepartmentExecutionRequest, *, now: datetime
    ) -> DepartmentAgentResult:
        child_trace_id = str(uuid4())
        recorder = TraceRecorder(
            trace_id=child_trace_id,
            user_id=request.user_id,
            session_id=request.parent_trace_id,
            query=request.query,
            created_at=now,
        )
        started = time.perf_counter()
        evidence: list[Evidence] = []
        answer = "当前有效政策证据不足，暂不作答。"
        citations: list[Citation] = []
        verified = False
        status = DepartmentExecutionStatus.RUNTIME_ERROR
        error_code: str | None = None
        runtime_backend = "safe_fallback"
        retrieval_metadata: dict[str, object] = {}

        try:
            with runtime_request_scope(
                trace_id=child_trace_id,
                agent_id=self._agent_id,
                dept_id=self._dept_id,
            ):
                try:
                    async with asyncio.timeout(request.deadline_ms / 1_000):
                        retrieval_started = time.perf_counter()
                        try:
                            evidence, retrieval_metadata = await self._retrieve(
                                rewritten_query=request.rewritten_query
                            )
                        except Exception:
                            status = DepartmentExecutionStatus.RETRIEVAL_ERROR
                            error_code = "retrieval_error"
                            return await self._finish(
                                recorder=recorder,
                                request=request,
                                child_trace_id=child_trace_id,
                                started=started,
                                status=status,
                                answer=answer,
                                citations=citations,
                                evidence=evidence,
                                verified=verified,
                                runtime_backend=runtime_backend,
                                error_code=error_code,
                                retrieval_metadata=retrieval_metadata,
                            )
                        recorder.record_node(
                            node="DepartmentRetrieve",
                            input_summary=request.rewritten_query,
                            output_summary=(
                                f"{len(evidence)} scoped evidence items / "
                                f"retrieval metadata={retrieval_metadata}"
                            ),
                            latency_ms=(time.perf_counter() - retrieval_started) * 1_000,
                        )
                        if not evidence:
                            status = DepartmentExecutionStatus.NO_EVIDENCE
                            error_code = "no_evidence"
                            return await self._finish(
                                recorder=recorder,
                                request=request,
                                child_trace_id=child_trace_id,
                                started=started,
                                status=status,
                                answer=answer,
                                citations=citations,
                                evidence=evidence,
                                verified=verified,
                                runtime_backend=runtime_backend,
                                error_code=error_code,
                                retrieval_metadata=retrieval_metadata,
                            )

                        answer_started = time.perf_counter()
                        draft = await self._answer_node.run(
                            request.query,
                            evidence,
                            memory_context=self._render_memory_context(request.memory_snapshot),
                        )
                        answer, citations = self._render(draft, evidence)
                        answer_events = self._drain_runtime_events()
                        runtime_backend = self._runtime_backend(answer_events, runtime_backend)
                        recorder.record_node(
                            node="DepartmentAnswer",
                            input_summary=request.query,
                            output_summary=answer[:500],
                            latency_ms=(time.perf_counter() - answer_started) * 1_000,
                            runtime_events=answer_events,
                        )
                        if not citations:
                            status = DepartmentExecutionStatus.RUNTIME_ERROR
                            error_code = "answer_abstained"
                            return await self._finish(
                                recorder=recorder,
                                request=request,
                                child_trace_id=child_trace_id,
                                started=started,
                                status=status,
                                answer=answer,
                                citations=citations,
                                evidence=evidence,
                                verified=verified,
                                runtime_backend=runtime_backend,
                                error_code=error_code,
                                retrieval_metadata=retrieval_metadata,
                            )

                        verify_started = time.perf_counter()
                        verification = await self._verify_node.run(
                            answer=answer,
                            citations=citations,
                            evidence=evidence,
                            claims=draft.claims,
                        )
                        verify_events = self._drain_runtime_events()
                        runtime_backend = self._runtime_backend(verify_events, runtime_backend)
                        recorder.record_node(
                            node="DepartmentVerify",
                            input_summary=f"{len(citations)} citations",
                            output_summary=(
                                "passed"
                                if verification.passed
                                else "; ".join(verification.warnings)
                            ),
                            latency_ms=(time.perf_counter() - verify_started) * 1_000,
                            fallback=not verification.passed,
                            runtime_events=verify_events,
                        )
                        verified = verification.passed
                        status = (
                            DepartmentExecutionStatus.SUCCESS
                            if verified
                            else DepartmentExecutionStatus.VERIFICATION_FAILED
                        )
                        error_code = None if verified else "verification_failed"
                except TimeoutError:
                    status = DepartmentExecutionStatus.TIMEOUT
                    error_code = "timeout"
        except Exception:
            status = DepartmentExecutionStatus.RUNTIME_ERROR
            error_code = "runtime_error"

        return await self._finish(
            recorder=recorder,
            request=request,
            child_trace_id=child_trace_id,
            started=started,
            status=status,
            answer=answer,
            citations=citations,
            evidence=evidence,
            verified=verified,
            runtime_backend=runtime_backend,
            error_code=error_code,
            retrieval_metadata=retrieval_metadata,
        )

    async def _finish(
        self,
        *,
        recorder: TraceRecorder,
        request: DepartmentExecutionRequest,
        child_trace_id: str,
        started: float,
        status: DepartmentExecutionStatus,
        answer: str,
        citations: list[Citation],
        evidence: list[Evidence],
        verified: bool,
        runtime_backend: str,
        error_code: str | None,
        retrieval_metadata: dict[str, object],
    ) -> DepartmentAgentResult:
        trace_status = (
            AnswerStatus.SUCCESS
            if status is DepartmentExecutionStatus.SUCCESS
            else AnswerStatus.ABSTAIN
        )
        base_trace = recorder.finish(
            status=trace_status,
            answer=answer,
            citation_cards=[self._citation_card(citation) for citation in citations],
        )
        runtime_events = [
            event for node in base_trace.nodes for event in node.runtime_events
        ]
        trace = replace(
            base_trace,
            parent_trace_id=request.parent_trace_id,
            trace_kind="child",
            execution_mode="department_agent",
            agent_id=self._agent_id,
            dept_id=self._dept_id,
            retrieval_hits=[item.chunk_id for item in evidence],
            retrieval_metadata=retrieval_metadata,
            verification={"passed": verified, "error_code": error_code},
            timings_ms={
                **{node.node: node.latency_ms for node in base_trace.nodes},
                "total": round((time.perf_counter() - started) * 1_000, 2),
            },
            errors=[error_code] if error_code is not None else [],
            runtime_fallbacks=[
                event
                for event in runtime_events
                if event.get("runtime_fallback_reason") is not None
            ],
        )
        await self._trace_store.save(trace)
        return DepartmentAgentResult(
            agent_id=self._agent_id,
            dept_id=self._dept_id,
            status=status,
            answer=answer,
            citations=[
                DepartmentCitation.from_citation(citation).model_copy(
                    update={"department": self._dept_id}
                )
                for citation in citations
            ],
            evidence_count=len(evidence),
            local_verifier_pass=verified,
            child_trace_id=child_trace_id,
            latency_ms=round((time.perf_counter() - started) * 1_000, 2),
            runtime_backend=runtime_backend,
            error_code=error_code,
        )

    @staticmethod
    def _render(draft: AnswerDraft, evidence: list[Evidence]) -> tuple[str, list[Citation]]:
        try:
            return render_cited_answer(draft.content, evidence, claims=draft.claims)
        except ValueError:
            return "当前有效政策证据不足，暂不作答。", []

    async def _retrieve(
        self, *, rewritten_query: str
    ) -> tuple[list[Evidence], dict[str, object]]:
        if isinstance(self._retriever, TraceableEvidenceRetriever):
            result = await self._retriever.retrieve_with_trace(
                queries=[rewritten_query],
                department_ids=self._retrieval_department_ids,
                limit=8,
            )
            trace = result.trace
            if is_dataclass(trace):
                return result.evidence, cast(dict[str, object], asdict(cast(Any, trace)))
            if isinstance(trace, dict):
                return result.evidence, {str(key): value for key, value in trace.items()}
            return result.evidence, {}
        return (
            await self._retriever.retrieve(
                queries=[rewritten_query], department_ids=self._retrieval_department_ids, limit=8
            ),
            {},
        )

    @staticmethod
    def _citation_card(citation: Citation) -> dict[str, object]:
        return {
            "id": citation.id,
            "chunk_id": citation.chunk_id,
            "document_id": citation.document_id,
            "version_id": citation.version_id,
            "title": citation.title,
            "department": citation.department,
            "status": citation.status.value,
            "excerpt": citation.excerpt,
            "document_number": citation.document_number,
            "written_date": citation.written_date,
            "source_url": citation.source_url,
        }

    @staticmethod
    def _render_memory_context(snapshot: dict[str, object]) -> str:
        """Pass bounded read-only context as non-evidence, never as citation material."""

        items = snapshot.get("items")
        if not isinstance(items, list):
            return ""
        rendered: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            memory_type = item.get("memory_type")
            content = item.get("content")
            if isinstance(memory_type, str) and isinstance(content, str):
                rendered.append(f"[{memory_type}] {content}")
        return "\n".join(rendered)[:8_000]

    def _drain_runtime_events(self) -> list[dict[str, str | float | None]]:
        drain = getattr(self._llm, "drain_runtime_audits", None)
        if not callable(drain):
            return []
        return [
            audit.as_trace_metadata()
            for audit in drain()
            if isinstance(audit, RuntimeInvocationAudit)
        ]

    @staticmethod
    def _runtime_backend(
        events: list[dict[str, str | float | None]], fallback: str
    ) -> str:
        if not events:
            return fallback
        backend = events[-1].get("runtime_backend_used")
        return str(backend) if backend is not None else fallback
