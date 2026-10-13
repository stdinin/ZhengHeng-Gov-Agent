# 评测与性能测试

| 目录 | 用途 |
| --- | --- |
| `evalsets/` | 政策问答冻结集与多部门编排测试用例 |
| `manifests/` | 公开政策数据集的版本、来源与采样配置 |
| [k6/](k6/README.md) | HTTP 负载测试脚本及指标口径 |

在仓库根目录运行：

```sh
uv run python scripts/run_eval.py --evalset evaluation/evalsets/policy_eval_v1.jsonl
```

真实检索评测使用 `scripts/run_public_eval.py`，多部门集成评测使用 `scripts/run_v11_multi_agent_eval.py`；运行前需准备对应的基础设施、数据与账户。

原始运行结果保存在本地 `runs/`，不纳入 Git。公开结果与限制见 [评测摘要](../docs/results/README.md)。
