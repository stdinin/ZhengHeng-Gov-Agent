# Final Validation Report

Validation date: 2026-10-09
Release target: `v1.0.0`

## Result

All P0 Phase 1–8 acceptance work is implemented, exercised, and passed against
the real local infrastructure. The optional external-provider profile is
implemented and unit-tested but deliberately remains deferred because no safe
`DEEPSEEK_API_KEY` was present in the current process.

| Phase | Implemented | Tested | Final status | Evidence |
|---|---|---|---|---|
| 1 Foundation | Yes | Yes | PASS | real health/readiness, seed and HTTP login |
| 2 Governance/Ingestion | Yes | Yes | PASS | real upload/index/publish/archive and IT-02 stale-index E2E |
| 3 Hybrid Retrieval | Yes | Yes | PASS | real BM25 + Milvus + RRF + reranker + canonical re-check |
| 4 Harness | Yes | Yes | PASS | IT-01, IT-03 and IT-06 real retrieval/citation/trace paths |
| 5 Memory | Yes | Yes | PASS | real Redis/Mongo memory repository boundary test |
| 6 Evolution | Yes | Yes | PASS | persisted trace → frozen replay → gray/rollback |
| 7 Public Eval | Yes | Yes | PASS | public corpus and frozen-eval artifacts generated |
| 8 Observability/Performance | Yes | Yes | PASS with resource guard | Prometheus validation and 10/50 VU FakeLLM artifacts; 200 VU not run |
| Optional Real-LLM E2E | Yes | Unit-tested only | DEFERRED | safe process key absent; not a P0 blocker |

## Actual Validation Commands and Results

| Command | Result |
|---|---|
| `uv run pytest backend/tests/unit -q -rA` | PASS — 117 passed |
| `uv run ruff check backend scripts` | PASS |
| `uv run mypy backend/app scripts` | PASS — 87 source files |
| `npm --prefix frontend run lint` | PASS |
| `npm --prefix frontend run test -- --run` | PASS — 1 file / 1 test |
| `npm --prefix frontend run build` | PASS |
| `uv run python scripts/run_integration_container.py --skip-build --hf-cache-dir C:/Users/XuWei/.cache/huggingface` | PASS — foundation/document/evolution 9, retrieval 4, harness 2 |
| `uv run python scripts/validate_observability.py --output runs/observability_final_v1` | PASS — generated `observability_validation.json` |
| `uv run python scripts/summarize_k6.py --raw runs/k6_10vu/raw.json ...` | PASS — regenerated summary from raw points |
| `uv run python scripts/summarize_k6.py --raw runs/k6_50vu/raw.json ...` | PASS — regenerated summary from raw points |

The integration runner's three groups all exercised real MongoDB, Redis,
OpenSearch and Milvus. CrossEncoder loading occurs in a Docker Linux child
process, but no retrieval implementation, candidate filtering, assertion, or
service call is mocked.

## IT Results

| Item | Result | Real acceptance evidence |
|---|---|---|
| IT-01 | PASS | fixed DAG chat uses real retrieval, persists full trace |
| IT-02 | PASS | v1 → v2 publish retains stale BM25/Milvus v1 entries; canonical ACTIVE re-check filters v1 and citations reference v2 only |
| IT-03 | PASS | citations map only to ACTIVE/current canonical evidence |
| IT-04 | PASS | feedback → bad case → strategy/replay/gray persistence in MongoDB |
| IT-05 | PASS | degrading strategy produces persisted experiment/execution/rollback record |
| IT-06 | PASS | real retrieval harness handles knowledge gap/abstention path |

## Infrastructure at Final Check

Docker Engine Client/Server: `29.6.1` / `29.6.1`.

| Service | Image/runtime version | Health at check |
|---|---|---|
| MongoDB | `quay.io/mongodb/mongodb-community-server:7.0-ubi9-slim`; server `7.0.43`; replica set `rs0` | healthy |
| Redis | `redis:7.4-alpine`; server `7.4.11` | healthy |
| OpenSearch | `public.ecr.aws/opensearchproject/opensearch:2.18.0`; server `2.18.0` | healthy |
| etcd | `quay.io/coreos/etcd:v3.5.16` | healthy |
| MinIO | `milvusdb/minio:RELEASE.2024-12-18T13-15-44Z` | healthy |
| Milvus | `zhengheng-milvus:2.6.25-healthfix`; runtime `2.6.25` | healthy (`/healthz` = `OK`) |
| API | `zhengheng-eval-runner:cpu` | healthy |
| Prometheus | `prom/prometheus:v3.5.0` | scraping API (`up=1`) |

## Public Eval and Ablation

Dataset: `salpt/chinatax-policy-corpus` revision
`db52ff69471dab17eef664fa7814d62798745720`; deterministic public manifest
contains 100 documents and 167 chunks. The frozen eval set has 40 cases
(30 factual, 10 knowledge-gap).

| Metric | Actual artifact value |
|---|---:|
| Recall@1 | 0.933333 |
| Recall@5 | 0.966667 |
| Recall@10 | 1.000000 |
| MRR | 0.955556 |
| Citation correctness | 0.125000 |
| Citation coverage | 1.000000 |
| Abstain/knowledge-gap accuracy | 0.000000 |
| Answer correctness | `NOT_AVAILABLE_FROM_DATASET` |
| Routing accuracy | `NOT_AVAILABLE_FROM_DATASET` |

The generated ablation artifact compares BM25, Dense, BM25 + Dense + RRF,
RRF + reranker, and full canonical ACTIVE re-check. It reports the actual
result; it does not assert that one method must win. The source run is
`runs/public_eval_v1_100docs/`; small versioned summaries are in
`docs/results/`.

## Phase 8 Evidence

Prometheus validation artifact: `runs/observability_final_v1/observability_validation.json`.
It recorded FakeLLM mode, a real retrieval-backed chat request, request counter
delta `1`, `up=1`, persisted abstain/verifier/error counters, and successful
Trace/metrics PII-redaction checks. Metric labels are restricted to fixed DAG
node names, not query/user/token values.

Performance profile name: **Harness / Retrieval Infrastructure Performance
(FakeLLM)**. It is not a real online-LLM E2E benchmark.

| Load | Requests | Throughput | P50 | P95 | P99 | Error rate |
|---|---:|---:|---:|---:|---:|---:|
| 10 VU / 5m | 1,699 | 5.702 RPS | 677.54 ms | 1,599.66 ms | 2,024.14 ms | 0 |
| 50 VU / 5m | 1,510 | 5.092 RPS | 8,197.08 ms | 15,761.33 ms | 17,284.83 ms | 0 |

Both raw k6 output and recalculated summaries are retained under `runs/`.
200 VU is `NOT_RUN_RESOURCE_GUARD`: 50 VU had zero request/check failures but
high tail latency and the host had limited available virtual memory. It is not
counted as a pass.

## External Provider Profile

`scripts/run_real_llm_e2e.py` provides a separate OpenAI-compatible DeepSeek
`deepseek-flash` profile. It requires a key only from the current process's
`DEEPSEEK_API_KEY`, performs 5 smoke cases before the full frozen set, and
records provider-reported token usage, estimated cost, latency, citation and
abstain metrics without serializing credentials or prompts. Its no-key guard,
usage accounting, and metrics have unit coverage. No real-provider call was
made for this release because no safe key was available; this does not affect
the FakeLLM Phase 8 P0 result.

## Known Limits and Compatibility Decisions

- A native Windows Python CrossEncoder load can raise `OSError 1455` when the
  Windows commit/pagefile budget is transiently low. The original native
  integration invocation failed this way; the required acceptance suite now
  runs unchanged in a Docker Linux subprocess and passed. No Windows, WSL or
  pagefile setting was modified.
- The final integration run emitted one unsuppressed third-party
  `jieba/pkg_resources` deprecation warning per model-using group. There was
  no PyMongo async-client finalizer warning after explicit shutdown was added.
- Docker registry/tag changes made for local compatibility: Mongo uses the
  official Quay `7.0-ubi9-slim` image to avoid a corrupted Docker Hub cache;
  Redis/OpenSearch use verified public ECR mirrors; Milvus uses the locally
  verified `zhengheng-milvus:2.6.25-healthfix` image. These do not change the
  application-facing service versions listed above.
