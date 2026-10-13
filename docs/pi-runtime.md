# Pi Runtime

V1.1 adds an internal TypeScript runtime at `services/pi-runtime`. It uses the
official `@earendil-works/pi-agent-core` and `@earendil-works/pi-ai` packages,
locked to `1.1.0` in `package-lock.json`, with Node `22.19.0`.

## Boundary

Pi Runtime is a constrained semantic-runtime boundary, not an autonomous
coding agent. It serves only:

```text
GET  /internal/health/live
GET  /internal/health/ready
POST /internal/v1/invoke
```

Every endpoint requires `X-Internal-Service-Token`. The Compose profile does
not publish port 8090 to the host; Orchestrator and Department Agent services
reach it over the Compose network only.

The request validator permits only the fixed semantic nodes (`intent`,
`rewrite`, `route`, `answer`, `verify`, `aggregate`, `reflect`) and rejects
tools, shell commands, filesystem paths, URL-fetch instructions, unknown
departments, oversized schemas, and malformed messages. Pi is always created
with an empty tool set.

## Runtime selection and safety

Python code calls the runtime through `PiRuntimeAdapter`, behind the common
`AgentRuntime` interface. Runtime events record requested backend, used
backend, latency, and fallback reason without placing raw query, user, or trace
identifiers in Prometheus labels.

If Pi returns a timeout, transport error, or invalid structured output, the
registry tries its configured fallback. If that also cannot provide a safe
answer, Answer and Verify fail closed: the policy harness abstains rather than
inventing a policy answer. Aggregate can only deterministically order and merge
already verified departmental sections.

## Validation profile

The shipped Compose profile uses `PI_RUNTIME_MODE=faux`. It executes the real
Pi Agent Core event loop and structured contract with a deterministic, tool-free
transport. The fixture preserves the original query for rewrite and applies
only the static department-keyword routing already governed by Python; it never
generates a policy fact. This validates the Pi code path, Python adapter,
schema contract, fallback, trace, and isolation boundaries.

It is **not** evidence that an external LLM provider has been called. An
external provider remains opt-in, must be supplied only through the runtime
environment, and must be reported separately when actually validated.

## Commands

The Docker build intentionally runs the Node tests and TypeScript build in a
Linux Node 22 container. This avoids reusing a Linux `esbuild` binary from a
previous container build in a Windows `node_modules` directory.

```powershell
docker compose --profile multi-agent build pi-runtime
docker compose --profile multi-agent up -d pi-runtime
docker compose --profile multi-agent ps pi-runtime
```

`backend/tests/integration/test_pi_runtime_container.py` is opt-in. Give it an
internal base URL and service token from the current process environment; never
write that token into source, artifact, or Git.
