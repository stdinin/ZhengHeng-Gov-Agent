# ZhengHeng Agent

多部门可信政务问答与反馈自进化系统。

## Core Architecture

- Governed document lifecycle with atomic version publication
- Hybrid RAG using BM25, dense retrieval, RRF, reranking, and canonical ACTIVE re-check
- Fixed Agent Harness with citation verification and persisted traces
- Layered working, session, profile, case, and strategy memory
- Feedback-driven strategy evolution with frozen-trace replay, gray release, and rollback
- Reproducible evaluation, Prometheus metrics, and performance harnesses

详细设计与验收边界见 [实现与验收规范](docs/IMPLEMENTATION_SPEC.md)。

## Current Status

`v1.0.0`

Phase 1–8 的 P0 实现与真实基础设施验收已经完成。Phase 8 使用 FakeLLM 测试
Harness/Retrieval Infrastructure Performance；它不代表真实在线 LLM 的端到端性能。
10 VU 和 50 VU 的原始 k6 artifacts 已生成并重算；200 VU 因本机资源保护未执行。逐项
状态、命令与保留项见 [DEFERRED_VALIDATION.md](DEFERRED_VALIDATION.md) 和
[FINAL_VALIDATION_REPORT.md](FINAL_VALIDATION_REPORT.md)。

公开评测 `public_eval_v1_100docs` 使用 100 篇公开政策文档、167 个 chunk 和 40 个冻结
eval case。核心指标来自真实生成的 run artifact；Citation Correctness 为 `0.125`、
Knowledge-gap Accuracy 为 `0.0`，未作修饰或替换。版本化的小型结果摘要位于
[docs/results](docs/results/README.md)。

## Development

要求 Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js/npm、Docker Desktop。

```text
copy .env.example .env
make setup
make infra-up
make seed
```

在两个终端分别运行：

```text
make backend
make frontend
```

后端默认地址为 `http://localhost:8000`，前端默认地址为
`http://localhost:5173`。`/api/v1/health/ready` 会真实探测 MongoDB、Redis、
OpenSearch 和 Milvus；依赖不可用时不会静默切换为内存实现。

## Validation

```text
uv run pytest backend/tests/unit -q
uv run ruff check backend scripts
uv run mypy backend/app
npm --prefix frontend run lint
npm --prefix frontend run test -- --run
npm --prefix frontend run build
make integration
```

真实评测与性能结果必须由生成的 artifacts 计算。FakeLLM 可用于确定性 Harness 测试，
但不得被描述为真实在线 LLM 端到端性能。`make integration` 在本机以 Docker Linux
子进程加载 CrossEncoder，继续连接同一组真实 MongoDB、Redis、OpenSearch、Milvus；
这是为规避 Windows 原生 PyTorch 的 transient pagefile mapping failure，而不是 mock 路径。
