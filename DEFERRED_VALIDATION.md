# Deferred Validation

## Current Recovery Status (2026-10-09)

`DEFERRED_INFRA_BLOCKER` is resolved at the Docker Engine level. The following
commands completed successfully against the Docker Desktop engine:

- `docker version` — both Client and Server were reported.
- `docker info` — returned Docker Desktop Linux/x86_64 engine information.
- `docker compose config --quiet` — Compose configuration validated.

All six real services are now healthy: `mongo` (single-node replica set `rs0`),
`redis`, `opensearch`, `etcd`, `minio`, and `milvus`.  The local Mongo topology
was corrected to a real replica set because document lifecycle operations use
transactions; the Compose `mongo-init` job performs the idempotent bootstrap.
No historical deferred item was changed to PASS without its exact command being
run against these services.

## Historical Blocker (Resolved)

`DEFERRED_INFRA_BLOCKER` — Docker Desktop 的 WSL2 引擎不可用。

- 观察日期：2026-10-09
- Docker backend 日志：执行 `wsl.exe -l -v --all` 时返回 `0xC000012D`。
- Windows 当时提交内存：约 92%；系统 Event ID 2004 记录了虚拟内存不足。
- 约束：在用户明确授权前，不调整分页文件、不修改 WSL 配置、不重启 Windows，且不再尝试启动 Docker Desktop。

该历史状态**不表示通过**。任何标注为 deferred/skipped 的测试都没有获得真实服务验证；不能用 mock 或内存实现替代其验收。

## Deferred Items

| 阶段 | 命令或测试 | 验收目的 | 当前状态 | 恢复后操作 |
|---|---|---|---|---|
| Phase 1 | `docker compose up -d mongo redis opensearch etcd minio milvus` | 启动真实依赖 | `PASS (2026-10-09): all six services healthy` | Mongo runs as `rs0`; retain health checks on future recovery |
| Phase 1 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_health_ready.py -q` | `/health/ready` 实际探测 Mongo、Redis、OpenSearch、Milvus | `PASS (2026-10-09): 1 passed` | Re-run after dependency version changes |
| Phase 1 | `uv run python scripts/seed_users.py` + real `/api/v1/auth/login` | 对真实 Mongo 幂等写入本地演示账户 | `PASS (2026-10-09): seed completed; login integration 1 passed` | Re-run only after resetting Mongo data |
| Phase 2 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_document_repository.py backend/tests/integration/test_document_api.py -q` | canonical fact store、唯一约束和原子发布 | `PASS (2026-10-09): 2 passed` | Re-run after lifecycle schema changes |
| Phase 2 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_document_indexer.py -q` | 真实上传版本的 Mongo/OpenSearch/Milvus reindex API consistency | `PASS (2026-10-09): 2 passed` | Re-run after index schema changes |
| Phase 2 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_document_version_e2e.py -q` | IT-02: v1/v2 upload → parse/chunk/index → atomic publish → stale-index canonical filter → citation/trace | `PASS (2026-10-09): 1 passed` | v1 BM25/Milvus entries were retained and final Citation referenced v2 only |
| Phase 3 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_retrieval_backends.py -q` | 真实 BM25、Milvus、canonical re-check、RRF + reranker | `PASS (2026-10-09): 4 passed` | Re-run after model/index schema changes |
| Phase 4 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_harness_real_retrieval.py -q` | IT-01/IT-03/IT-06: 真实 fixed DAG、canonical re-check、Citation、Trace、chat API | `PASS (2026-10-09): 2 passed` | FakeLLM generated structured responses only; retrieval remained real |
| Phase 1–6 | `uv run python scripts/run_integration_container.py --skip-build --hf-cache-dir C:/Users/XuWei/.cache/huggingface` | Windows 上统一真实 integration 验收（Linux 进程隔离 CrossEncoder） | `PASS (2026-10-09): foundation/document/evolution 9 + retrieval 4 + harness 2` | Docker Linux 子进程连接同一组真实服务；Windows native PyTorch 本轮曾报 `OSError 1455`，未使用 mock；未再出现 PyMongo async-client finalizer warning |
| Phase 5 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_memory_evolution_persistence.py::test_real_redis_and_mongo_memory_repositories_preserve_memory_boundaries -q` | 五层 Memory 的真实读写、Redis TTL、用户删除与事实隔离 | `PASS (2026-10-09): real Mongo/Redis test passed` | 已通过真实服务；不得将该结果外推为检索或 E2E 验收 |
| Phase 6 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_memory_evolution_persistence.py::test_real_mongo_persists_feedback_through_gray_rollback -q` | IT-04/IT-05 持久化子链：真实 Mongo feedback → badcase → strategy → replay gate → gray → rollback | `PASS (2026-10-09): real Mongo test passed` | 已通过真实服务；包含实际双臂 50/50 劣化记录与 ROLLED_BACK 持久化 |
| Phase 6 | `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_evolution_frozen_replay.py -q` | 从真实持久化 Harness Trace 冻结输入，重新执行检索并计算 replay metrics、gray 与 rollback | `PASS (2026-10-09): 1 passed` | improvement 进入 gray；degradation 自动 rollback；experiment/execution/rollback 均写入真实 Mongo |
| Phase 7 | `uv run python scripts/run_public_eval.py ...` + artifact integrity validation | 公开政策语料真实导入、冻结 Eval 与 retrieval ablation | `PASS (2026-10-09): 100 documents / 167 chunks / 40 cases` | 实际指标保存在 `runs/public_eval_v1_100docs/`；小型摘要版本化到 `docs/results/` |
| Phase 8 | `uv run python scripts/validate_observability.py --output runs/observability_final_v1` | Prometheus scrape、metrics delta、PII redaction | `PASS (2026-10-09): up=1; request delta=1; trace/metrics PII checks passed` | FakeLLM only generates the answer; the request executes real retrieval infrastructure |
| Phase 8 | `uv run python scripts/summarize_k6.py --raw runs/k6_10vu/raw.json ...` and `...k6_50vu...` | 从真实 k6 raw points 计算 throughput/P50/P95/P99/error rate | `PASS (2026-10-09): 10 VU and 50 VU artifacts revalidated; error rate 0` | Profile is strictly `Harness / Retrieval Infrastructure Performance (FakeLLM)`; 200 VU is `NOT_RUN_RESOURCE_GUARD`, not a PASS |
| Optional Real-LLM | `uv run python scripts/run_real_llm_e2e.py --pricing-period peak --phase smoke` | DeepSeek `deepseek-flash` 5-case smoke, then frozen generation subset | `DEFERRED: no safe DEEPSEEK_API_KEY in the current process` | Profile implementation and secret-boundary/unit tests pass; it is non-P0 and must be run only after a rotated key is supplied through the process environment |

## Recovery Order

1. 确认 `docker version` 同时显示 Client 与 Server，且 `docker info` 返回成功。
2. 执行 `docker compose config --quiet`，然后启动 Compose 服务并等待各服务健康。
3. 运行 `RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_health_ready.py -q`。
4. 执行演示用户 seed，使用真实 `/api/v1/auth/login` 验证。
5. 初始化 Mongo 索引、OpenSearch 索引和 Milvus collection，导入公开 demo policy docs，确认 canonical ACTIVE 版本与两类检索索引一致。
6. 运行 Phase 2、Phase 3 integration tests，然后运行 IT-01 / IT-03 / IT-06；每一项只在真实服务上标记为通过。
7. 验证 Phase 5 Redis/Mongo Memory repositories，再运行 Phase 6 feedback → badcase → strategy replay / gray / rollback 测试。
8. 公开语料导入、完整 Eval Run、ablation、Prometheus scrape 与 10/50 VU k6 已完成并保存真实 artifacts；200 VU 仅在资源保护条件满足时追加执行。
9. 若要运行可选 Real-LLM profile，先通过当前进程环境提供**已轮换**的 `DEEPSEEK_API_KEY`，先跑 5-case smoke，再跑 frozen generation subset；不得将该 key 写入文件、日志、Trace、artifact 或 Git。
