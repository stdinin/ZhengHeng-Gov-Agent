# 系统设计图

## 业务时序图与功能结构图

图件覆盖政策问答的业务交互和模块组成：

- `zhengheng-sequence.png` / `.svg` / `.drawio`：四阶段、70 条消息的业务时序图。
- `zhengheng-functions.png` / `.svg` / `.drawio`：六个子系统的黑白树形功能结构图。
- `zhengheng-business-diagrams.drawio`：上述两图合并为两个可编辑页面。
- `build_business_diagrams.py`：生成业务时序图与功能结构图，依赖 `resvg-py` 和 Pillow；重新运行覆盖同名输出，手动修改 draw.io 后请先另存。

时序依据：`api/auth.py`、`frontend/src/pages/Login.tsx`、`api/documents.py`、`ingestion/indexer.py`、`agents/chat_service.py`、`agents/memory.py`、`memory/context.py`、`agents/orchestrator.py`、`agents/department_service.py`、`agents/aggregator.py`、`retrieval/hybrid.py`、`evolution/service.py`。后端路径均相对 `backend/app/`。

图采用逻辑参与者：FastAPI、全局编排、入库与反馈服务合并为后端泳道；Python 检索逻辑、BGE 模型、OpenSearch 和 Milvus 合并为检索与索引泳道。三类部门 Agent 用一个泳道表达相同流程，以并行注释注明 fan-out。回放内部流程折叠为自调用。省略部分底层读取返回，不表示无返回值。文档发布展示成功分支，问答补充部分失败与拒答说明。

功能结构图归纳代码能力，不表示全部功能都有前端页面；管理操作当前可由 API / 脚本完成。用户登录使用 sessionStorage 保存 JWT。

系统架构图采用五层布局：客户端、服务层、业务层、公共技术层、基础设施与工具。图件依据 V1.1 源码与配置整理，描述系统设计，不表示线上运行状态。

## 文件

- `zhengheng-architecture.png`：3280 × 2700 高清图片，适合文档和演示。
- `zhengheng-architecture.svg`：可缩放矢量图，Logo 内嵌，不依赖外链。
- `zhengheng-architecture.drawio`：原生可编辑形状、文本、连线和内嵌 Logo。
- `build_diagram.py`：生成脚本，需要 Python 与 `resvg-py`；首次运行下载素材，后续使用本地缓存。重新运行会覆盖本目录同名导出文件，包括 draw.io 文件，手动编辑后应先另存副本。

## 架构依据

| 图中内容 | 当前源码 / 配置依据 |
| --- | --- |
| React、Vite、TypeScript 与页面入口 | `frontend/package.json`、`frontend/src/App.tsx` |
| FastAPI、REST、JWT / RBAC | `pyproject.toml`、`backend/app/main.py`、`backend/app/security/` |
| 全局编排与税务 / 人社 / 住建 Agent | `backend/app/agents/`、`docs/multi-agent.md`、`docker-compose.yml` |
| 固定部门作用域、并发、超时、结果聚合 | `backend/app/agents/department_service.py`、`orchestrator.py`、`aggregator.py` |
| BM25 + Dense → RRF → 重排 → canonical ACTIVE 复核 | `backend/app/retrieval/hybrid.py`、`backend/app/storage/document_repository.py` |
| 文档解析、分块、索引、版本生命周期 | `backend/app/ingestion/` |
| 引用验证与拒答 | `backend/app/harness/policy.py`、`citations.py`、`nodes.py` |
| 分层记忆、根 / 子 Trace | `backend/app/memory/`、`backend/app/observability/tracing.py`、`backend/app/agents/memory.py` |
| 反馈、策略 DSL、冻结回放、审核、灰度和回滚 | `backend/app/evolution/`、`backend/app/api/evolution.py` |
| Pi Agent Core、受控语义节点 | `services/pi-runtime/package.json`、`docs/pi-runtime.md` |
| BGE-M3、BGE Reranker、可配置 LLM 接口 | `backend/app/config.py`、`backend/app/runtime/` |
| MongoDB / Redis / OpenSearch / Milvus / MinIO / etcd | `docker-compose.yml`、`backend/app/storage/` |
| Prometheus、Kubernetes / Helm、评测工具 | `deploy/`、`evaluation/k6/`、`backend/app/evaluation/` |

图中 Hybrid RAG 是三个部门 Agent 各自执行的共同链路，不是额外部署的共享 Agent。数据平面为共享基础设施，通过服务端固定部门身份限制检索范围。MinIO 和 etcd 是 Milvus 的基础依赖，不表示文档上传直接接入 MinIO。

V1.1 多 Agent 为可选模式，默认保留 V1.0 单 Agent Harness。Pi Compose 配置默认 Faux；图中没有假设已调用某个具体商业模型。Kubernetes / Helm 已有配置，但运行验收存在保留项。管理与评测前端页面目前含占位提示，因此没有将其画成完整运营后台。隔离实验中的 `evidence_sufficiency.py` 没有被画成默认线上链路。

## Logo 来源

使用各技术项目的品牌矢量素材。React、FastAPI、Python、Node.js、MongoDB、Redis、Docker、Prometheus、Kubernetes 来自 [Devicon 素材库](https://github.com/devicons/devicon)；OpenSearch 来自 [官方品牌素材](https://github.com/opensearch-project/project-website/tree/main/assets/brand/SVG/Mark)；Milvus 来自 [官方 Artwork 仓库](https://github.com/milvus-io/artwork)。每个下载地址保存在 `assets/sources.json`。标识商标归各自所有者，保留原形和原色。

## 重新生成

在项目根目录执行（需要安装 `resvg-py` 和 Pillow）：

```sh
python docs/architecture/build_diagram.py
python docs/architecture/build_business_diagrams.py
```

高清图片、SVG、draw.io 源文件和 Logo 来源记录纳入版本管理；脚本生成的低分辨率预览与分阶段截图仅供本地检查，由 `.gitignore` 排除。
