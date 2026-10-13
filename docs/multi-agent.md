# V1.1 Multi-Agent Runtime

V1.1 keeps the V1.0 single-agent harness intact and adds an opt-in,
deterministically governed multi-agent execution mode. It is not a system of
autonomous agents negotiating with arbitrary tools.

```text
External chat request
  -> Global Orchestrator: Intent / Rewrite / static Registry validation
  -> concurrent Department Agent calls (tax, hrss, housing)
  -> local Hybrid RAG + canonical ACTIVE re-check + local Verify
  -> verified section aggregation + global Verify + citation dedupe
  -> root result, root/child Trace hierarchy, one root episodic-memory write
```

## Roles and scopes

`SERVICE_ROLE=orchestrator` accepts `/api/v1/chat`. A Department Agent runs
the same backend image with immutable `SERVICE_ROLE=department_agent`,
`AGENT_ID`, and `DEPT_ID`. The internal request model deliberately has no
department override field. Each service constructs a retrieval filter from its
own immutable department identity; the tax compatibility alias `dept_tax` is
also a fixed service-side mapping.

The registry is static. It permits only the configured tax, HRSS, and housing
services and applies the bounded `DEPARTMENT_AGENT_TIMEOUT_MS` from Settings to
each default definition. V1.1 local Compose uses 20 seconds after measured
CPU-only BGE-M3 service calls exceeded the inherited 12-second default. This
is still per-agent bounded timeout isolation, not an unbounded retry.

## Failure and data governance

The dispatcher uses bounded concurrent calls. One timeout or client failure is
recorded in `failed_departments` while verified remaining sections can form a
partial response. All failed/no-evidence agents produce an abstention. The
Aggregator discards failed local verification, refuses archived citations,
deduplicates canonical `(document, version, chunk)` citations, and does not
accept runtime prose as a new policy fact.

Root traces hold selected departments, child IDs, aggregation, partial/failure
details, and final verification. Child traces point to their parent and retain
actual BM25, dense, RRF, reranker, and canonical-filter stage counts. The root
builds one read-only memory snapshot; only it writes the final episodic item.
Evolution retains its declarative strategy DSL and may attribute agent timeout,
partial failure, aggregation, routing, and cross-department failures without
auto-publishing a strategy.

## Compose validation

The profile is opt-in and does not change the normal V1.0 topology:

```powershell
docker compose --profile multi-agent config --quiet
docker compose --profile multi-agent up -d --build
uv run python scripts/seed_users.py
# Seed the three V1.1 documents through scripts/seed_v11_multi_agent_demo.py
# from a Linux container when native Windows BGE-M3 construction is affected.
$env:V11_MULTI_AGENT_BASE_URL = 'http://127.0.0.1:8010'
uv run pytest backend/tests/integration/test_multi_agent_compose.py -q
uv run python scripts/run_v11_multi_agent_eval.py --base-url $env:V11_MULTI_AGENT_BASE_URL
```

`test_multi_agent_compose.py` is an opt-in real HTTP test: it uses actual
Compose services and actual MongoDB, OpenSearch, Milvus, Redis, and persisted
traces. Pi Faux may supply semantic fixtures, but it never replaces retrieval
or persistence.

The frozen `evaluation/evalsets/multi_agent_eval.jsonl` contains four single-department, six
cross-department, and two fault cases. The runner creates a timestamped
`runs/v11_multi_agent_eval_*/` artifact with a manifest hash, raw results,
metrics, and Markdown report. Its fault cases pause and stop real Department
Agent containers, restoring them in `finally`; it is marked
`INTEGRATION_FIXTURE`, not a public-policy benchmark or a real-LLM quality
claim.
