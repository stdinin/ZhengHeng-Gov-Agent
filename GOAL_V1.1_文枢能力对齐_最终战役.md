# GOAL V1.1：政衡 Agent「文枢能力对齐」最终实施规格

> **用途**：本文件直接交给 Codex Goal / Work 模式执行。  
> **目标**：在不扩张产品边界、不推翻 V1.0 已通过实现的前提下，只补齐原“文枢”最有辨识度、而政衡 V1.0 尚未完整覆盖的三项能力：**Pi Agent Runtime、真正的多部门 Multi-Agent、最小可验证 Kubernetes / Helm / HPA 部署**。  
> **原则**：这是最后一次功能扩展。完成本文件后封版，不再继续堆 Agent 概念。

---

# 0. Codex 执行总指令

你正在维护仓库 **ZhengHeng / 政衡 Agent**。当前 `v1.0.0` 已正式冻结并完成真实验收，本轮目标是实现 **V1.1「文枢能力对齐」**。

必须严格遵守：

1. **不得移动、覆盖、重打 `v1.0.0` tag。**
2. 不得推翻 V1.0 已经真实通过的 Document Governance、Hybrid Retrieval、Harness、Memory、Evolution、Eval、Prometheus、k6 主链路。
3. 本轮只做三件事：
   - Pi Agent Runtime Adapter；
   - 真正的多部门 Multi-Agent；
   - 最小可验证 K8s / Helm / HPA。
4. 不新增 A2A、动态 Agent 生成、Agent 社会、RL、自动写代码、自动 Shell、复杂工作流 DSL 等无关功能。
5. 每一个“完成”都必须有真实测试或可复现 smoke test；不能因为代码存在就标记 PASS。
6. 已通过的 V1.0 测试必须继续保持通过。
7. 若遇到 Windows / WSL / Docker / pagefile / 系统代理问题，只记录并请求用户授权；不得自行改系统级配置。
8. 不得删除失败测试、降低断言、用 mock 冒充真实服务。
9. 所有内部 Agent / Runtime 失败必须可追踪、可降级、可审计。
10. 完成后必须产出 `FINAL_V1_1_VALIDATION_REPORT.md`。

推荐执行方式：

```text
读取本文件
  ↓
确认 V1.0 基线
  ↓
Phase A：Runtime 抽象 + Pi Runtime
  ↓
Phase B：Department Agent Service
  ↓
Phase C：Global Orchestrator + Multi-Agent
  ↓
Phase D：Trace / Memory / Evolution / Metrics 接线
  ↓
Phase E：K8s / Helm / HPA
  ↓
Phase F：全量回归 + V1.1 报告
```

除非遇到需要用户授权的系统级操作，否则不要在每个小问题上停下来等待确认。

---

# 1. V1.0 已冻结基线

本轮开始前，以下事实视为 **已完成，不重复重写**：

- `v1.0.0` 已推送并冻结；
- 后端 unit tests：117 passed；
- Ruff：PASS；
- mypy：87 source files PASS；
- 前端 lint / Vitest / production build：PASS；
- 真实 integration：`9 + 4 + 2 passed`；
- Mongo / Redis / OpenSearch / etcd / MinIO / Milvus 已真实集成；
- Mongo 为单节点副本集，版本发布事务可用；
- Hybrid Retrieval 已包含：OpenSearch BM25 + Milvus Dense + RRF + BGE CrossEncoder + Mongo canonical ACTIVE re-check；
- IT-02 已真实验证：保留 v1 stale index 后，最终只能引用 v2 ACTIVE；
- Harness 固定 DAG、Citation、Trace、ABSTAIN 已真实通过；
- 五层 Memory 已实现；
- Feedback → Bad Case → Strategy → Replay → Gray → Rollback 已实现并有真实闭环；
- Prometheus scrape / metric growth / PII redaction PASS；
- k6 10 / 50 VU FakeLLM infrastructure artifacts 已保存，0% error；
- Public Eval 已有 100 docs / 167 chunks / 40 frozen cases artifact；
- 200 VU 为 `NOT_RUN_RESOURCE_GUARD`；
- Real-LLM DeepSeek profile 代码存在但因无安全 key 未作为 P0 验收；
- Windows CrossEncoder native pagefile 问题已通过 Docker Linux 子进程隔离真实测试解决，不是 mock。

**禁止为了 V1.1 重构这些已通过链路。**

---

# 2. V1.1 的唯一目标

V1.1 只补齐下列能力矩阵：

| 能力 | 文枢设计 | 政衡 V1.0 | V1.1 目标 |
|---|---|---|---|
| 固定 Harness DAG | 有 | 已有 | 保持 |
| Hybrid RAG | 有 | 已有且更实 | 保持 |
| 五层 Memory | 有 | 已有 | 保持 |
| Feedback 自进化 | 有 | 已有且真实 replay/rollback | 保持 |
| Pi Agent Runtime | 有 | 未接 | **补齐** |
| Department Agent 独立 Service | 有 | 只有 dept route | **补齐** |
| Global Orchestrator 并行调用 | 有 | 未实现 | **补齐** |
| 单部门超时隔离 | 有 | 未实现 | **补齐** |
| Aggregation + Global Verify | 有设计语义 | 未实现 | **补齐** |
| Kubernetes / Helm | 有 | 未完成 | **补齐** |
| HPA | 有 | 未完成 | **补齐最小可验证版本** |
| Prometheus / k6 | 有 | 已有 | 复用，不重写 |

完成后，系统应准确描述为：

> **基于固定 Harness + Pi Runtime 的多部门 Multi-Agent 可信政务 RAG 与反馈自进化系统。**

---

# 3. 明确非目标

本轮**禁止**实现：

- 动态创建 Agent；
- LLM 自主决定创建多少子 Agent；
- Agent-to-Agent 自由对话；
- A2A protocol；
- MCP Server 大规模接入；
- Agent society / blackboard / negotiation；
- RL / Agentic RL；
- 模型训练或微调；
- Skill 自动写 Python；
- 任意 Bash / 文件系统工具暴露给 Pi Runtime；
- 浏览器自动化；
- OpenTelemetry；
- 新数据库；
- 新向量数据库；
- 替换 OpenSearch / Milvus；
- 自定义 Prometheus Adapter 指标扩缩容；
- Service Mesh；
- Istio；
- 复杂 K8s 生产 HA；
- 再造一个新的 Eval 系统；
- 为了简历好看而虚构吞吐、Pod 数量、成功率。

**目标不是把系统做成无限扩张的 Agent 平台，只需完整覆盖文枢主要能力。**

---

# 4. V1.1 最终架构

```text
                                   User
                                    │
                             POST /api/v1/chat
                                    │
                          ┌─────────▼─────────┐
                          │ Global Orchestrator│
                          └─────────┬─────────┘
                                    │
                     Intent → Rewrite → Route
                                    │
                            RouteDecision
                         1..N Departments
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
      ┌───────▼────────┐    ┌───────▼────────┐    ┌───────▼────────┐
      │ Tax Dept Agent │    │ HRSS Dept Agent│    │ Housing Agent  │
      │  independent   │    │  independent   │    │  independent   │
      │    service     │    │    service     │    │    service     │
      └───────┬────────┘    └───────┬────────┘    └───────┬────────┘
              │                     │                     │
              │    Department-scoped Hybrid RAG          │
              │  BM25 + Dense + RRF + Reranker           │
              │      + Canonical ACTIVE Re-check         │
              │                     │                     │
              └──────────────┬──────┴──────┬──────────────┘
                             │             │
                       Dept Answers + Citations
                             │
                       ┌─────▼─────┐
                       │ Aggregator │
                       └─────┬─────┘
                             │
                       Global Verify
                             │
                  Citation / Trace / Memory
                             │
                           Answer

Semantic nodes / Agent reasoning:

Python Harness ──HTTP──> Pi Runtime Service
       │                     │
       │                 pi-agent-core
       │                     │
       └──── fallback ── OpenAICompatibleRuntime / deterministic safe fallback
```

底层继续复用：

```text
MongoDB     Redis     OpenSearch     Milvus     Prometheus
  │          │            │            │            │
canonical   memory       BM25         Dense        metrics
```

---

# 5. 关键设计原则

## 5.1 Multi-Agent 的定义

V1.1 只有满足以下条件才能称为 Multi-Agent：

1. 存在多个独立 Department Agent 实例；
2. 每个 Agent 有独立 `agent_id` / `dept_id`；
3. 每个 Agent 强制独立知识边界；
4. 每个 Agent 可独立超时 / 失败；
5. Global Orchestrator 可并行调用多个 Agent；
6. 每个 Agent 产生独立 child Trace；
7. Global Orchestrator 汇总多个 Agent 输出；
8. 最终统一 Global Verify。

仅仅 `Route → dept_id → 同一 Harness` **不算 Multi-Agent**。

## 5.2 Pi Runtime 的定位

Pi Runtime **不是系统控制平面**。

Pi 只负责不确定性语义能力：

- Intent semantic classification；
- Query Rewrite；
- Department routing structured decision；
- Department answer organization；
- Global aggregation；
- Semantic Verify；
- Reflect failure attribution。

Pi **不得直接负责**：

- DB 权限；
- ACTIVE / ARCHIVED 判断；
- `DEPT_ID` 强制约束；
- 检索过滤；
- Mongo transaction；
- Strategy publish / rollback；
- Stable bucket；
- HPA；
- K8s；
- 任意 Shell / 文件系统操作。

即：

```text
LLM / Pi = semantic decisions
Python   = deterministic governance
```

---

# 6. Pi Runtime：技术选择固定

## 6.1 使用官方 TypeScript Runtime

Pi 主线当前为 TypeScript / Node.js。V1.1 不使用不明来源 Python 克隆包。

实现为独立内部服务：

```text
services/pi-runtime/
```

默认依赖：

```text
@earendil-works/pi-agent-core
@earendil-works/pi-ai
```

实施开始时执行：

```bash
npm view @earendil-works/pi-agent-core version
npm view @earendil-works/pi-ai version
```

规则：

- 两个包必须使用**相同发布系列 / 兼容版本**；
- 在 `package-lock.json` 中精确锁定；
- 不允许 `latest` 漂移；
- 若当前环境已安装并验证另一官方 Pi package 名称，先核实 upstream，再迁移；
- 不使用第三方同名 Python `pi-agent-core` 替代官方实现。

当前规格目标 Node：

```text
Node >= 22.19.0, < 23
```

建立：

```text
services/pi-runtime/.nvmrc
```

建议固定当前可用 Node 22.x LTS patch。

## 6.2 Pi Runtime 为内部服务，不暴露公网

端口默认：

```text
8090
```

仅提供：

```text
GET  /internal/health/live
GET  /internal/health/ready
POST /internal/v1/invoke
```

必须要求：

```http
X-Internal-Service-Token: <shared-secret>
```

无 token：401。

---

# 7. Pi Runtime 请求/响应契约

## 7.1 Request

```json
{
  "request_id": "uuid",
  "trace_id": "uuid",
  "agent_id": "tax-agent",
  "dept_id": "tax",
  "node": "answer",
  "system_prompt": "...",
  "messages": [
    {"role": "user", "content": "..."}
  ],
  "response_schema": {
    "type": "object"
  },
  "timeout_ms": 20000,
  "metadata": {
    "strategy_id": null,
    "strategy_version": null
  }
}
```

约束：

- `node` 只能来自白名单；
- `dept_id` 必须来自已注册部门；
- `response_schema` 大小限制；
- `messages` 总长度受限；
- 不接受任意 tools；
- 不接受 Shell command；
- 不接受 file path；
- 不接受 URL fetching instruction。

## 7.2 Response

```json
{
  "request_id": "uuid",
  "ok": true,
  "output_text": "...",
  "output_json": {},
  "provider": "deepseek",
  "model": "...",
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "latency_ms": 1234,
  "finish_reason": "stop",
  "event_count": 12,
  "error": null
}
```

失败：

```json
{
  "ok": false,
  "error": {
    "code": "PI_RUNTIME_TIMEOUT",
    "message": "...",
    "retryable": true
  }
}
```

---

# 8. Python AgentRuntime 抽象

现有 Python backend 中新增统一接口。

建议：

```text
backend/app/runtime/
├── base.py
├── fake.py
├── openai_compatible.py
├── pi.py
├── registry.py
└── errors.py
```

接口语义：

```python
class AgentRuntime(Protocol):
    async def invoke(
        self,
        *,
        node: RuntimeNode,
        agent_id: str,
        dept_id: str | None,
        trace_id: str,
        system_prompt: str,
        messages: list[RuntimeMessage],
        response_model: type[T],
        timeout_ms: int,
    ) -> RuntimeResult[T]: ...

    async def healthcheck(self) -> RuntimeHealth: ...
    async def close(self) -> None: ...
```

必须保留：

- `FakeRuntime`：unit / deterministic integration；
- 现有 OpenAI-compatible runtime；
- 新 `PiRuntimeAdapter`。

## 8.1 Runtime 选择

环境变量：

```env
AGENT_RUNTIME_BACKEND=pi
AGENT_RUNTIME_FALLBACK=openai_compatible
PI_RUNTIME_BASE_URL=http://pi-runtime:8090
PI_RUNTIME_TIMEOUT_MS=20000
PI_RUNTIME_CONNECT_TIMEOUT_MS=3000
INTERNAL_SERVICE_TOKEN=change-me
```

测试环境可以：

```env
AGENT_RUNTIME_BACKEND=fake
```

## 8.2 Fallback 规则

Pi 调用失败时：

```text
PiRuntime
   │
   ├─ success → continue
   │
   └─ timeout / 5xx / malformed structured output
                  ↓
        OpenAICompatibleRuntime
                  │
          ├─ success → continue
          └─ fail
                  ↓
            safe fallback
```

Safe fallback：

| Node | 最终安全降级 |
|---|---|
| Intent | `UNKNOWN` |
| Rewrite | 使用原 query |
| Route | deterministic whitelist route / 无法确定则 abstain |
| Answer | **ABSTAIN，不允许伪造答案** |
| Aggregate | deterministic section merge，仅合并已验证 dept answer |
| Verify | fail-closed |
| Reflect | 标记 `UNCLASSIFIED`，不生成 strategy |

Trace 必须记录：

```text
runtime_backend_requested
runtime_backend_used
runtime_fallback_reason
runtime_latency_ms
```

---

# 9. Pi Runtime 安全约束

Pi Agent **不得获得以下工具**：

```text
bash
shell
file read/write
browser
HTTP arbitrary fetch
Mongo direct client
Redis direct client
OpenSearch direct client
Milvus direct client
Kubernetes client
```

V1.1 中 Pi 的角色是**受控 Agent Runtime**，不是 autonomous coding agent。

若 pi-agent-core 强制需要 tool list，则传空工具集或仅提供严格 schema 的内部 semantic completion tool；不得为了“Agent 感”给它额外权限。

---

# 10. Multi-Agent：服务角色

同一个 Python backend image 支持两种角色：

```env
SERVICE_ROLE=orchestrator
```

或：

```env
SERVICE_ROLE=department_agent
DEPT_ID=tax
AGENT_ID=tax-agent
```

禁止为每个部门复制一份代码仓库。

## 10.1 Orchestrator

职责：

- external `/api/v1/chat`；
- Intent；
- Rewrite；
- Route；
- Agent registry；
- parallel dispatch；
- timeout isolation；
- result aggregation；
- Global Verify；
- final Citation / Trace；
- final episodic memory write；
- Feedback / Evolution 入口。

## 10.2 Department Agent

职责：

- 强制 `DEPT_ID`；
- department-scoped retrieval；
- RRF / Reranker；
- canonical ACTIVE re-check；
- department answer；
- local semantic/deterministic verify；
- child Trace；
- 返回 citations。

不得：

- 改写自己的 `DEPT_ID`；
- 查询其他部门；
- 直接向用户返回最终全局回答；
- 自己发布 strategy；
- 自己写最终 episodic memory。

---

# 11. Department Agent Registry

新增：

```text
backend/app/agents/
├── models.py
├── registry.py
├── client.py
├── orchestrator.py
├── aggregator.py
└── department_service.py
```

静态 registry 即可，不做动态创建。

模型：

```python
class DepartmentAgentDefinition(BaseModel):
    agent_id: str
    dept_id: str
    display_name: str
    base_url: str
    enabled: bool = True
    timeout_ms: int = 12000
    max_concurrency: int = 8
```

来源优先级：

```text
1. env / Helm values
2. config file
```

不要求在 V1.1 做数据库动态注册中心。

默认 demo departments：

```text
tax
hrss
housing
```

实际名称可适配当前仓库已有 department seed，但必须至少有 3 个可注册 Agent。

---

# 12. RouteDecision

现有 route node 升级为：

```python
class RouteDecision(BaseModel):
    mode: Literal["single", "multi", "abstain"]
    departments: list[str]
    confidence: float
    reason: str
```

硬约束：

```text
1 <= len(departments) <= MULTI_AGENT_MAX_DEPARTMENTS
```

默认：

```env
MULTI_AGENT_MAX_DEPARTMENTS=3
```

所有模型输出必须经过 Python whitelist 校验：

- 未注册部门移除；
- 禁用部门移除；
- 空结果 → abstain；
- 超过 3 个 → 按置信度 / deterministic priority 截断。

LLM 不能凭空创建部门。

---

# 13. Global Orchestrator 执行流程

```text
Query
 ↓
Intent
 ↓
Rewrite
 ↓
RouteDecision
 ↓
Registry validation
 ↓
Dispatch 1..N Department Agents
 ↓
Wait with per-agent timeout
 ↓
Collect success / timeout / failure
 ↓
Aggregate successful verified results
 ↓
Global Verify
 ↓
Citation dedupe
 ↓
Final Trace
 ↓
Answer / Partial Answer / Abstain
```

## 13.1 并发

使用：

```python
asyncio.gather(..., return_exceptions=True)
```

或等价结构，并配合 semaphore。

默认：

```env
ORCHESTRATOR_MAX_PARALLEL=4
DEPARTMENT_AGENT_TIMEOUT_MS=12000
```

不能串行调用多个部门。

## 13.2 Timeout isolation

场景：

```text
Tax Agent     1.8s success
HRSS Agent    timeout
Housing Agent 2.5s success
```

最终：

- Tax + Housing 结果可继续；
- `partial=true`；
- `failed_departments=[hrss]`；
- 不允许因为一个 Agent timeout 导致全部请求 500。

若**全部** Agent timeout / fail / 无证据：

```text
ABSTAIN
```

---

# 14. Department Agent 内部执行链

Department Agent 不再重复 Intent / global Route。

内部固定：

```text
DepartmentRequest
 ↓
Apply immutable DEPT_ID
 ↓
Query / Strategy / Memory snapshot
 ↓
Hybrid Retrieval
 ↓
RRF
 ↓
Reranker
 ↓
Canonical ACTIVE Re-check
 ↓
Answer (Pi Runtime)
 ↓
Local Verify
 ↓
DepartmentAgentResult
```

强制 retrieval filter：

```text
department_id == service DEPT_ID
```

不能使用 request body 中的 dept_id 覆盖 service 的 `DEPT_ID`。

---

# 15. Department Agent 内部 API

仅内部网络暴露：

```text
GET  /internal/health/live
GET  /internal/health/ready
POST /internal/v1/execute
```

Request：

```json
{
  "parent_trace_id": "uuid",
  "request_id": "uuid",
  "query": "...",
  "rewritten_query": "...",
  "user_id": "...",
  "memory_snapshot": {},
  "strategy_snapshot": {},
  "deadline_ms": 12000
}
```

注意：request **不允许**传入可覆盖 service `DEPT_ID` 的字段。

Response：

```json
{
  "agent_id": "tax-agent",
  "dept_id": "tax",
  "status": "success",
  "answer": "...",
  "citations": [],
  "evidence_count": 5,
  "local_verifier_pass": true,
  "child_trace_id": "uuid",
  "latency_ms": 1840,
  "runtime_backend": "pi"
}
```

失败状态：

```text
timeout
no_evidence
runtime_error
retrieval_error
verification_failed
```

---

# 16. Aggregator

新增 `MultiAgentAggregator`。

输入：

```text
list[DepartmentAgentResult]
```

处理：

1. 丢弃 `local_verifier_pass=false` 的结果；
2. citation 按 `(document_id, version_id, chunk_id)` 去重；
3. 保留 department attribution；
4. Pi Runtime 负责语言组织；
5. Pi Runtime 失败时执行 deterministic merge；
6. 最终必须经过 Global Verify。

不得让 Aggregator 创造不存在于任何 Department Result 中的政策事实。

建议结构化输出：

```json
{
  "summary": "...",
  "sections": [
    {
      "dept_id": "tax",
      "content": "...",
      "citation_ids": ["..."]
    }
  ]
}
```

Global Verify 必须检查：

- section claim 是否可由对应 citation 支持；
- citation 是否 ACTIVE；
- citation department 是否符合来源 Agent；
- 不支持的 claim 删除或触发 ABSTAIN / partial。

---

# 17. External Chat API 兼容

不得破坏 V1.0 `/api/v1/chat` 基本响应字段。

新增可选字段：

```json
{
  "answer": "...",
  "citations": [],
  "trace_id": "...",
  "abstained": false,
  "orchestration": {
    "mode": "multi",
    "requested_departments": ["tax", "hrss"],
    "completed_departments": ["tax"],
    "failed_departments": [
      {"dept_id": "hrss", "reason": "timeout"}
    ],
    "partial": true,
    "fanout": 2
  }
}
```

旧客户端忽略 `orchestration` 仍应正常工作。

---

# 18. Trace 层级

V1.1 Trace 必须支持 parent / child。

Root Trace：

```text
trace_id
execution_mode = multi_agent
route_decision
selected_departments
child_trace_ids
aggregation
partial
failed_departments
runtime_fallbacks
final_verify
```

Child Trace：

```text
trace_id
parent_trace_id
agent_id
dept_id
retrieval_candidates
reranked_candidates
canonical_filter
answer
citations
local_verify
runtime_backend
latency
status
```

若现有 `traces` schema 缺字段，以**向后兼容、nullable**方式扩展，不做破坏性迁移。

---

# 19. Memory 与 Multi-Agent 的关系

不要重写五层 Memory。

规则：

## 19.1 Root 构建 Memory Snapshot

Global Orchestrator 调用现有 `MemoryContextBuilder` 一次，生成**只读 snapshot**。

Department Agents 接收 snapshot，但不能直接写最终 episodic memory。

## 19.2 Department scope

- Organizational Memory：允许按 `dept_id` 过滤；
- Procedural Memory / Strategy：允许 global + dept-scoped；
- User Semantic Memory：只读；
- Working Memory：请求级；
- Episodic Memory：最终由 Orchestrator 在回答完成后写一次。

避免多个 Agent 并发写同一用户 memory 造成竞态。

---

# 20. Evolution 与 Multi-Agent 的关系

继续复用 V1.0 Evolution。

Bad Case 新增可选维度：

```text
agent_id
dept_id
orchestration_stage
```

新增可归因类别：

```text
routing_error
agent_timeout
agent_partial_failure
aggregation_error
cross_department_conflict
```

Strategy scope：

```text
global
orchestrator
department
```

若现有 strategy schema 无 scope，新增 nullable/default 字段：

```python
scope: Literal["global", "orchestrator", "department"] = "global"
dept_id: str | None = None
```

禁止重新设计 V1.0 Strategy DSL。

---

# 21. Observability

复用现有 Prometheus。

新增 metrics：

```text
zhengheng_runtime_invocations_total{backend,node,status}
zhengheng_runtime_fallback_total{from_backend,to_backend,node}
zhengheng_runtime_latency_seconds{backend,node}

zhengheng_orchestrator_requests_total{mode,status}
zhengheng_orchestrator_fanout_size
zhengheng_orchestrator_partial_total

zhengheng_department_agent_calls_total{dept_id,status}
zhengheng_department_agent_latency_seconds{dept_id}
zhengheng_department_agent_timeout_total{dept_id}
```

禁止 label：

```text
query
user_id
trace_id
name
phone
raw document title
```

以避免 PII / 高基数。

---

# 22. Minimal Admin UI 补充

只加一个最小页面/面板：

```text
Agent Network
```

显示：

- Orchestrator status；
- Pi Runtime status；
- Department Agent 列表；
- dept_id；
- health；
- runtime backend；
- recent latency；
- timeout count；
- 最近一次 child trace 链接。

不需要画复杂动态图谱。

现有 Trace Explorer 增加：

```text
Root Trace
  ├─ Tax Agent child trace
  ├─ HRSS Agent child trace
  └─ Housing Agent child trace
```

---

# 23. Repository 目录变更

建议最终增加：

```text
ZhengHeng/
├── backend/
│   └── app/
│       ├── runtime/
│       │   ├── base.py
│       │   ├── fake.py
│       │   ├── openai_compatible.py
│       │   ├── pi.py
│       │   ├── registry.py
│       │   └── errors.py
│       ├── agents/
│       │   ├── models.py
│       │   ├── registry.py
│       │   ├── client.py
│       │   ├── orchestrator.py
│       │   ├── aggregator.py
│       │   └── department_service.py
│       └── api/
│           └── internal_agents.py
│
├── services/
│   └── pi-runtime/
│       ├── package.json
│       ├── package-lock.json
│       ├── tsconfig.json
│       ├── .nvmrc
│       ├── Dockerfile
│       └── src/
│           ├── server.ts
│           ├── agent.ts
│           ├── schema.ts
│           ├── auth.ts
│           └── health.ts
│
├── deploy/
│   ├── helm/
│   │   └── zhengheng/
│   │       ├── Chart.yaml
│   │       ├── values.yaml
│   │       ├── values-kind.yaml
│   │       └── templates/
│   │           ├── orchestrator-deployment.yaml
│   │           ├── orchestrator-service.yaml
│   │           ├── department-agent-deployments.yaml
│   │           ├── department-agent-services.yaml
│   │           ├── pi-runtime-deployment.yaml
│   │           ├── pi-runtime-service.yaml
│   │           ├── configmap.yaml
│   │           ├── hpa.yaml
│   │           └── _helpers.tpl
│   └── kind/
│       └── kind-config.yaml
│
├── scripts/
│   ├── run_v11_integration.py
│   ├── pi_runtime_smoke.py
│   ├── multi_agent_smoke.py
│   └── k8s_smoke.py
│
└── docs/
    ├── pi-runtime.md
    ├── multi-agent.md
    └── kubernetes.md
```

可以根据现有结构调整文件名，但职责边界必须保持。

---

# 24. 环境变量

新增 `.env.example`：

```env
# Execution mode
AGENT_EXECUTION_MODE=multi
MULTI_AGENT_MAX_DEPARTMENTS=3
ORCHESTRATOR_MAX_PARALLEL=4
DEPARTMENT_AGENT_TIMEOUT_MS=12000

# Runtime
AGENT_RUNTIME_BACKEND=pi
AGENT_RUNTIME_FALLBACK=openai_compatible
PI_RUNTIME_BASE_URL=http://localhost:8090
PI_RUNTIME_TIMEOUT_MS=20000
PI_RUNTIME_CONNECT_TIMEOUT_MS=3000
INTERNAL_SERVICE_TOKEN=replace-me

# Service role
SERVICE_ROLE=orchestrator
AGENT_ID=orchestrator
DEPT_ID=

# Department registry (local dev)
DEPARTMENT_AGENT_TAX_URL=http://localhost:8101
DEPARTMENT_AGENT_HRSS_URL=http://localhost:8102
DEPARTMENT_AGENT_HOUSING_URL=http://localhost:8103
```

Docker / K8s 内使用 service DNS 覆盖 URL。

真实 LLM key 不写进仓库。

---

# 25. Docker Compose V1.1

现有 infra compose 不推翻。

新增 profile：

```text
multi-agent
```

服务：

```text
pi-runtime
orchestrator
department-agent-tax
department-agent-hrss
department-agent-housing
```

每个 Department Agent 使用同一 backend image，仅环境变量不同。

例如：

```yaml
department-agent-tax:
  image: zhengheng-backend:local
  environment:
    SERVICE_ROLE: department_agent
    AGENT_ID: tax-agent
    DEPT_ID: tax
```

要求：

- healthcheck；
- depends_on 只负责启动排序，不代替 readiness；
- 不额外复制 Mongo/OpenSearch/Milvus；
- 全部共享同一 canonical data plane，但由 `DEPT_ID` 强制隔离。

---

# 26. Kubernetes / Helm 目标

## 26.1 只做最小可验证部署

V1.1 K8s 只要求：

```text
1 Orchestrator Deployment
1 Pi Runtime Deployment
N Department Agent Deployments
对应 ClusterIP Services
ConfigMap
Secret refs
HPA
readiness/liveness
```

不做生产 HA。

## 26.2 Helm values

示例：

```yaml
orchestrator:
  replicas: 1
  autoscaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 3
    targetCPUUtilizationPercentage: 70

piRuntime:
  replicas: 1

agents:
  - id: tax-agent
    deptId: tax
    enabled: true
    replicas: 1
    autoscaling:
      enabled: true
      minReplicas: 1
      maxReplicas: 3
      targetCPUUtilizationPercentage: 70

  - id: hrss-agent
    deptId: hrss
    enabled: true
    replicas: 1
    autoscaling:
      enabled: true
      minReplicas: 1
      maxReplicas: 3
      targetCPUUtilizationPercentage: 70

  - id: housing-agent
    deptId: housing
    enabled: true
    replicas: 1
    autoscaling:
      enabled: true
      minReplicas: 1
      maxReplicas: 3
      targetCPUUtilizationPercentage: 70
```

## 26.3 Secret

Helm Chart 只能引用 Secret：

```text
zhengheng-secrets
```

不得把 API key 写入：

```text
values.yaml
Git
ConfigMap
README
```

## 26.4 HPA

本轮 HPA 使用 Kubernetes CPU metric 即可。

**不实现 Prometheus Adapter custom metric autoscaling。**

理由：文枢主要能力是 HPA / 弹性入口；自定义 metric adapter 不是本轮必要核心，而且 V1.0 已有 Prometheus 观测。

---

# 27. Kind 本地验收

优先使用：

```text
kind
```

建立：

```text
deploy/kind/kind-config.yaml
```

Codex 应自动检测：

```bash
kind version
kubectl version --client
helm version
```

若未安装，**不要修改 Windows 系统级配置**；给出可执行安装命令并标记 blocker，等待用户授权。

如果均可用：

```text
kind create cluster --name zhengheng
helm lint ...
helm template ...
helm upgrade --install ...
kubectl wait ...
```

验收至少包括：

```text
orchestrator Ready
pi-runtime Ready
3 department agents Ready
Services 可解析
Orchestrator 能调用至少 2 个 Department Agents
```

---

# 28. HPA 最小验证

如果 kind metrics-server 可用：

1. 安装/启用 metrics-server；
2. `kubectl get hpa` 能显示 CPU metric；
3. 对一个 Department Agent 发起短时负载；
4. 若本机资源允许，观察 `desiredReplicas > 1`；
5. 若资源保护阻止真实 scale-out，则：
   - Helm/HPA object validation 可以 PASS；
   - runtime scale-out 必须标记 `NOT_RUN_RESOURCE_GUARD`；
   - 不得伪造 1→N Pod 数据。

本轮不要求 20 Pod。

---

# 29. Pi Runtime 测试

新增测试编号：

## PI-01 Runtime health

- `/internal/health/ready` 返回 ready；
- Python `PiRuntimeAdapter.healthcheck()` 通过。

## PI-02 Structured output

- 使用 Pi runtime 执行结构化 Intent 或 Rewrite；
- schema validation 通过；
- Trace 记录 backend=pi。

## PI-03 Timeout fallback

强制 Pi 超时：

```text
Pi timeout
 ↓
Fallback runtime
 ↓
成功
```

Trace 必须记录 fallback。

## PI-04 Fail closed

Pi + fallback 均失败时 Answer node：

```text
ABSTAIN
```

不得输出伪造答案。

## PI-05 Tool isolation

证明 Pi Runtime 没有 bash/file/browser tools。

---

# 30. Multi-Agent 测试

## MA-01 Single department

Query 只属于 tax：

- Route=single；
- 只调用 tax-agent；
- fanout=1；
- 结果 citation 全属于 tax scope。

## MA-02 Cross-department parallel fanout

Query 涉及两个部门：

- Route=multi；
- 至少 2 Department Agents 并发；
- 两个 child Trace；
- aggregate 后返回。

必须证明不是串行：

```text
wall latency < 两个独立 latency 简单相加的合理阈值
```

不要硬编码绝对速度，基于测试 stub delay 验证并发语义。

## MA-03 Department isolation

故意让 tax query 中包含 hrss 关键词：

- tax-agent 仍不能返回 hrss document；
- retrieval 强制由 service `DEPT_ID` 过滤。

## MA-04 Timeout isolation

一个 agent sleep/timeout：

- 其他 Agent 成功；
- root 返回 partial；
- HTTP 不应 500；
- failed_departments 记录 timeout。

## MA-05 All fail

全部失败：

```text
ABSTAIN
```

## MA-06 Citation dedupe

两个 Agent 引用同一 canonical chunk：

- 最终 citation 只出现一次；
- attribution 可保留多个 source agent。

## MA-07 Global Verify

一个 Department Agent 返回 unsupported claim：

- Global Verify 必须过滤/拒绝；
- 不允许直接拼接输出。

## MA-08 Root/child Trace

Root Trace 能找到所有 child trace；child 能反查 parent。

## MA-09 Memory write ownership

两个 Department Agent 完成后：

- 最终 episodic memory 只由 Orchestrator 写一次。

## MA-10 Evolution attribution

Agent timeout / route error 可生成对应 badcase attribution，但不得自动生成危险 strategy。

---

# 31. K8s / Helm 测试

## K8S-01 Helm static

```bash
helm lint deploy/helm/zhengheng
helm template ...
```

必须 PASS。

## K8S-02 Kind smoke

至少：

```text
orchestrator Ready
pi-runtime Ready
tax-agent Ready
hrss-agent Ready
housing-agent Ready
```

## K8S-03 Internal routing

从 Orchestrator pod：

- 能访问 agent ClusterIP；
- 能执行 multi-agent smoke。

## K8S-04 Pod failure isolation

删除一个 Department Agent pod 或让其临时 unavailable：

- 其他 Agent 仍可响应；
- Orchestrator partial / abstain 逻辑正确；
- Deployment 自动恢复 pod。

## K8S-05 HPA object

`kubectl get hpa` 正常，metric target 可解析。

真实 scale-out 若资源允许则执行；否则如实标注 resource guard。

---

# 32. Multi-Agent Evaluation

不要重新做大规模研究。

新增一个**工程验证级** frozen fixture：

```text
multi_agent_eval.jsonl
```

至少 12 cases：

```text
4 single-department
6 cross-department
2 timeout/failure
```

可以使用明确标记为 `INTEGRATION_FIXTURE` 的测试政策文档；不得把这 12 条包装成真实大规模 benchmark。

必须计算：

```text
route_set_exact_match
cross_department_completion_rate
partial_response_correctness
citation_department_scope_accuracy
timeout_isolation_success_rate
```

可选记录：

```text
single-router latency
multi-agent latency
```

仅作 V1.1 工程验证，不替代 V1.0 公开语料 Eval。

---

# 33. Single-Agent 回退模式

V1.1 必须保留 V1.0 单 Agent 模式：

```env
AGENT_EXECUTION_MODE=single
```

Multi-Agent：

```env
AGENT_EXECUTION_MODE=multi
```

理由：

- 回滚；
- regression；
- baseline；
- 故障降级。

不允许删除 V1.0 single harness。

---

# 34. Regression 要求

完成 V1.1 后，必须重新运行：

```text
V1.0 unit tests
Ruff
mypy
frontend lint
frontend Vitest
frontend build
V1.0 unified integration runner
IT-01 ~ IT-06
V1.0 public eval smoke / artifact read
Prometheus validation
```

V1.1 新增：

```text
PI-01 ~ PI-05
MA-01 ~ MA-10
K8S-01 ~ K8S-05
```

V1.0 已通过的指标不允许因 V1.1 莫名下降且不解释。

如果执行模式为 `single`，V1.0 behavior 应保持兼容。

---

# 35. 实施阶段

# Phase A：Runtime 抽象 + Pi Runtime

任务：

1. 抽象 Python `AgentRuntime`；
2. 迁移现有 Fake/OpenAI runtime 到统一接口；
3. 建 `services/pi-runtime`；
4. 接官方 pi-agent-core / pi-ai；
5. 建 internal invoke API；
6. Python `PiRuntimeAdapter`；
7. fallback；
8. Runtime metrics；
9. PI tests。

**Phase A DoD：**

```text
PI-01 ~ PI-05 PASS
现有 V1.0 tests PASS
```

若真实 provider key 不存在：

- 允许用可控本地/fake transport 验证 pi-agent-core runtime loop；
- 但最终报告必须区分 `Pi Runtime code path verified` 与 `Real external LLM provider verified`；
- 不得声称真实 DeepSeek/Pi 在线调用已通过。

---

# Phase B：Department Agent Service

任务：

1. service role；
2. immutable `DEPT_ID`；
3. internal API；
4. department scoped retrieval；
5. local answer / verify；
6. child Trace；
7. Docker Compose 3 agents；
8. Registry / client。

**Phase B DoD：**

```text
MA-01
MA-03
child trace tests
3 Department Agent health PASS
```

---

# Phase C：Global Orchestrator

任务：

1. RouteDecision；
2. parallel dispatch；
3. timeout isolation；
4. aggregation；
5. Global Verify；
6. final citation；
7. partial response；
8. all-fail ABSTAIN；
9. root/child traces；
10. minimal Agent Network UI。

**Phase C DoD：**

```text
MA-02 ~ MA-10 PASS
```

---

# Phase D：Memory / Evolution / Observability 接线

任务：

1. read-only memory snapshot；
2. root episodic write；
3. strategy scope；
4. multi-agent badcase attribution；
5. metrics；
6. PII labels audit；
7. V1.0 Evolution regression。

**Phase D DoD：**

```text
V1.0 evolution tests PASS
multi-agent memory ownership PASS
Prometheus new metrics visible
```

---

# Phase E：K8s / Helm / HPA

任务：

1. Helm Chart；
2. Orchestrator Deployment / Service；
3. Pi Runtime Deployment / Service；
4. range 生成 Department Agent Deployment / Service；
5. readiness / liveness；
6. Secret refs；
7. HPA；
8. kind smoke；
9. pod failure isolation。

**Phase E DoD：**

```text
K8S-01 ~ K8S-05
```

允许 `runtime scale-out` 因 resource guard 不执行，但 HPA 静态/metric 验证必须通过。

---

# Phase F：最终回归与封版

任务：

1. V1.0 full regression；
2. V1.1 full tests；
3. multi-agent fixture eval；
4. docs；
5. final report；
6. README 更新；
7. CHANGELOG；
8. Git clean check。

通过后建议：

```text
v1.1.0
```

**不得覆盖 v1.0.0。**

---

# 36. Definition of Done

V1.1 只有同时满足以下条件才算完成：

## Pi Runtime

- [ ] 官方 Pi runtime package 已真实集成；
- [ ] Python Adapter 可调用；
- [ ] structured output；
- [ ] timeout；
- [ ] fallback；
- [ ] fail-closed；
- [ ] Trace / metrics；
- [ ] 无危险 tools。

## Multi-Agent

- [ ] 至少 3 个独立 Department Agent Service；
- [ ] immutable `DEPT_ID`；
- [ ] Global Orchestrator；
- [ ] 多部门并行；
- [ ] 单 Agent timeout isolation；
- [ ] partial response；
- [ ] all-fail abstain；
- [ ] Aggregator；
- [ ] Global Verify；
- [ ] Citation dedupe；
- [ ] parent/child Trace；
- [ ] Memory ownership 正确；
- [ ] Evolution attribution 正确。

## Deployment

- [ ] Docker Compose multi-agent profile；
- [ ] Helm lint PASS；
- [ ] Helm template PASS；
- [ ] kind/minimal K8s smoke（环境允许时）；
- [ ] Orchestrator Ready；
- [ ] Pi Runtime Ready；
- [ ] 3 Department Agents Ready；
- [ ] HPA manifests；
- [ ] HPA metric 可读或明确 resource guard；
- [ ] Pod failure isolation。

## Regression

- [ ] V1.0 unit 全通过；
- [ ] Ruff；
- [ ] mypy；
- [ ] frontend；
- [ ] unified integration；
- [ ] IT-01~IT-06；
- [ ] Prometheus；
- [ ] V1.0 Eval artifact 可复现；
- [ ] PI tests；
- [ ] MA tests；
- [ ] K8s tests。

## Documentation

- [ ] `docs/pi-runtime.md`；
- [ ] `docs/multi-agent.md`；
- [ ] `docs/kubernetes.md`；
- [ ] README 架构图更新；
- [ ] `.env.example`；
- [ ] `FINAL_V1_1_VALIDATION_REPORT.md`。

---

# 37. Final Validation Report 模板

最终报告至少写：

```markdown
# ZhengHeng V1.1 Final Validation Report

## 1. Git
- base: v1.0.0
- final commit:
- tag:

## 2. Runtime
- pi-agent-core package/version:
- pi-ai package/version:
- Node version:
- backend mode:
- real provider verified: YES/NO
- fallback verified: YES/NO

## 3. Multi-Agent
- registered agents:
- single-dept tests:
- cross-dept tests:
- timeout isolation:
- partial response:
- all-fail abstain:
- trace hierarchy:

## 4. K8s
- helm lint:
- helm template:
- kind smoke:
- ready pods:
- HPA:
- scale-out:

## 5. Regression
- backend unit:
- ruff:
- mypy:
- frontend:
- V1.0 integration:
- V1.1 integration:

## 6. Multi-Agent Fixture Eval
- cases:
- route_set_exact_match:
- cross_department_completion_rate:
- citation_department_scope_accuracy:
- timeout_isolation_success_rate:

## 7. Known Limitations

## 8. NOT RUN / DEFERRED

## 9. Resume-safe Claims
只列真实可复现事实。
```

---

# 38. README 最终架构描述

README 不得写成“多个 Agent 自主协商”。

准确描述：

> ZhengHeng uses a deterministic global harness to route a request to one or more statically registered department agents. Department agents run in isolated services with immutable department scopes, execute trusted hybrid retrieval, and return verified evidence-backed results. The global orchestrator executes agents concurrently, tolerates individual timeouts, aggregates successful results, and performs a final verification before producing the response. Semantic nodes can run through Pi Agent Runtime with controlled fallback, while permissions, retrieval scope, version validity, rollout, and rollback remain deterministic application logic.

中文：

> 政衡采用确定性的全局 Harness，将请求路由至一个或多个静态注册的部门 Agent。各部门 Agent 以独立 Service 运行，并由不可变 `DEPT_ID` 强制限制知识边界，执行可信 Hybrid RAG 后返回经验证、带引用的结果。Global Orchestrator 并行调度部门 Agent，对单 Agent 超时进行隔离，聚合成功结果后再执行全局 Verify。Intent、Rewrite、Answer、Aggregate、Reflect 等语义节点可通过 Pi Agent Runtime 执行；权限、事实有效性、检索边界、灰度和回滚仍由确定性代码治理。

---

# 39. 简历安全边界

V1.1 完成后可以写：

- “基于 Pi Agent Runtime 的受控 Harness”；
- “多部门 Multi-Agent 并行协同”；
- “Global Orchestrator”；
- “独立 Department Agent Service”；
- “timeout isolation / partial result”；
- “Helm / HPA / K8s 最小部署”；

前提是相应测试真实 PASS。

不能写：

- 20 Pod，如果没跑；
- 200 VU，如果没跑；
- 生产集群，如果只是 kind；
- 真实政府系统交付；
- Agent 自主创建 Agent；
- Pi 实际在线模型调用，如果只有 adapter/fake transport 验证；
- 未实际生成的性能数字。

---

# 40. Codex 决策优先级

出现歧义时：

1. 不破坏 V1.0；
2. 正确性；
3. 部门隔离；
4. fail-closed；
5. 真实可验证；
6. Trace 可审计；
7. fallback；
8. 测试；
9. K8s 可部署；
10. UI。

如果时间不足：

可以不做：

- HPA 真实 scale-out；
- Agent Network 漂亮图；
- Real external LLM provider smoke（如果没有安全 key）。

不能删：

- Pi Runtime Adapter；
- Department Agent 独立 Service；
- Global Orchestrator；
- 并发；
- timeout isolation；
- aggregation；
- Global Verify；
- parent/child Trace；
- Helm Chart；
- HPA manifest；
- V1.0 regression。

---

# 41. Git 与版本纪律

1. `v1.0.0` 永远保持现有 commit；
2. 不 force-push；
3. 不重写历史；
4. V1.1 完成前不要提前打 tag；
5. 所有测试通过后再生成 `v1.1.0`；
6. 若某一必选能力未真实验收，版本报告必须写 `PARTIAL`，不能假装完整。

---

# 42. 最终演示脚本

## Demo A：Pi Runtime

1. 发起一个单部门政策问题；
2. Trace 展示 `runtime_backend=pi`；
3. 强制 runtime failure；
4. 展示 fallback；
5. 不影响 deterministic retrieval / citation。

## Demo B：Multi-Agent

问题同时涉及两个部门：

```text
“高校毕业后创业可以申请什么扶持，同时税收上有哪些优惠？”
```

展示：

```text
RouteDecision → [hrss, tax]
       ↓
HRSS Agent + Tax Agent parallel
       ↓
2 child traces
       ↓
Aggregator
       ↓
Global Verify
       ↓
Final Answer + citations
```

## Demo C：Timeout isolation

人为让一个 Agent 超时：

```text
Agent A success
Agent B timeout
```

最终仍返回 A 的可信结果，`partial=true`。

## Demo D：Department isolation

让 tax Agent 收到包含其他部门关键词的 query，证明 retrieval 不能越过 tax `DEPT_ID`。

## Demo E：K8s

```text
kubectl get pods
kubectl get svc
kubectl get hpa
```

展示：

- Orchestrator；
- Pi Runtime；
- 3 Department Agents；
- HPA。

删除一个 Department Agent pod，Deployment 自动恢复；Orchestrator 在恢复窗口内保持 timeout isolation。

---

# 43. 本轮结束条件

只有以下闭环真实成立才结束：

```text
Pi Runtime
   +
Department Agent Services
   +
Global Orchestrator
   +
Parallel Dispatch
   +
Timeout Isolation
   +
Aggregation
   +
Global Verify
   +
Parent/Child Trace
   +
Helm/K8s/HPA
   +
V1.0 Full Regression
```

完成后立即封版。

**不要继续增加新技术点。**

---

# 44. 给 Codex 的第一条执行指令

将本文件放在仓库根目录后，直接使用下面这段：

> 严格按照 `GOAL_V1.1_文枢能力对齐_最终战役.md` 执行。本轮是在已冻结并通过真实验收的 V1.0 上做最后一次能力对齐，只实现 Pi Agent Runtime Adapter、真正的多部门 Multi-Agent、最小可验证 Kubernetes/Helm/HPA 三块。不要扩功能，不要重写已经通过的 V1.0 主链。先确认 git/v1.0.0/现有测试基线，再从 Phase A 开始；每完成一个 Phase 运行对应测试并修复到通过，再进入下一 Phase。真实外部 LLM key 缺失时不得伪造在线验证，但不能因此跳过 Pi Runtime 代码路径和 fallback 验证。除涉及 Windows/WSL/分页文件/系统代理等系统级修改外，不要停下来等待我逐项确认。最终必须产出 `FINAL_V1_1_VALIDATION_REPORT.md`，只有真实执行通过的项目才能标记 PASS。完成本文件后封版，不再增加新的 Agent 功能。

---

# 45. Pi 上游信息记录

实施时仅用于依赖核验，不是项目宣传内容：

- Pi Agent Core upstream repository/package family：`@earendil-works/pi-agent-core`
- LLM abstraction：`@earendil-works/pi-ai`
- 上游仓库：`https://github.com/earendil-works/pi`
- 旧的 `@mariozechner/pi-agent-core` npm 包已提示迁移到 `@earendil-works/pi-agent-core`。

Codex 应在实施开始时再次核验 package metadata，并把**实际安装版本**写入 lockfile 与最终报告。

---

# 46. 最后一句

**V1.0 已经把“文枢”的可信 RAG、Harness、Memory、Evolution、Eval、观测与压测做实；V1.1 只补 Pi、真正 Multi-Agent 和最小 K8s 部署。三块完成即停。**
