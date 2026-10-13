"""Errors deliberately exposed to callers as runtime failures, not policy answers."""


class AgentRuntimeError(RuntimeError):
    """The configured semantic runtime could not produce a trusted result."""


class PiRuntimeError(AgentRuntimeError):
    """The internal Pi service was unavailable or returned an invalid contract."""
