"""Request-scoped runtime identity and audit records with no prompt or credential data."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeRequestContext:
    trace_id: str
    agent_id: str
    dept_id: str | None


@dataclass(frozen=True, slots=True)
class RuntimeInvocationAudit:
    trace_id: str
    agent_id: str
    dept_id: str | None
    runtime_backend_requested: str
    runtime_backend_used: str
    runtime_fallback_reason: str | None
    runtime_latency_ms: float

    def as_trace_metadata(self) -> dict[str, str | float | None]:
        return {
            "runtime_backend_requested": self.runtime_backend_requested,
            "runtime_backend_used": self.runtime_backend_used,
            "runtime_fallback_reason": self.runtime_fallback_reason,
            "runtime_latency_ms": round(self.runtime_latency_ms, 2),
        }


_request_context: ContextVar[RuntimeRequestContext | None] = ContextVar(
    "runtime_request_context", default=None
)
_audits: ContextVar[tuple[RuntimeInvocationAudit, ...]] = ContextVar(
    "runtime_invocation_audits", default=()
)


@contextmanager
def runtime_request_scope(
    *, trace_id: str, agent_id: str, dept_id: str | None
) -> Iterator[RuntimeRequestContext]:
    """Bind immutable identity for a single harness request and discard its audits on exit."""

    context = RuntimeRequestContext(trace_id=trace_id, agent_id=agent_id, dept_id=dept_id)
    context_token = _request_context.set(context)
    audits_token = _audits.set(())
    try:
        yield context
    finally:
        _audits.reset(audits_token)
        _request_context.reset(context_token)


def current_runtime_request() -> RuntimeRequestContext:
    context = _request_context.get()
    if context is None:
        return RuntimeRequestContext(
            trace_id="runtime-trace-unbound",
            agent_id="runtime-unbound",
            dept_id=None,
        )
    return context


def record_runtime_audit(audit: RuntimeInvocationAudit) -> None:
    _audits.set((*_audits.get(), audit))


def drain_runtime_audits() -> list[RuntimeInvocationAudit]:
    audits = list(_audits.get())
    _audits.set(())
    return audits
