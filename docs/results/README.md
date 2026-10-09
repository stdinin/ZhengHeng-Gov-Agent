# Reproducible Result Summaries

本目录只保存从真实运行 artifacts 提取的小型、可审计结果。原始预测、trace、模型缓存、
公开语料缓存与大型性能输出不进入版本库。

## public_eval_v1_100docs

- Dataset: `salpt/chinatax-policy-corpus`
- Dataset revision: `db52ff69471dab17eef664fa7814d62798745720`
- Documents: 100
- Chunks: 167
- Frozen eval cases: 40（30 factual，10 knowledge-gap）
- Metrics source: `runs/public_eval_v1_100docs/metrics.json`
- Ablation source: `runs/public_eval_v1_100docs/ablation_results.json`

| Metric | Value |
|---|---:|
| Recall@1 | 0.9333333333 |
| Recall@5 | 0.9666666667 |
| Recall@10 | 1.0000000000 |
| MRR | 0.9555555556 |
| Citation Correctness | 0.1250000000 |
| Citation Coverage | 1.0000000000 |
| Knowledge-gap Accuracy | 0.0000000000 |
| Answer Correctness | NOT_AVAILABLE_FROM_DATASET |
| Routing Accuracy | NOT_AVAILABLE_FROM_DATASET |

这些指标描述当前冻结评测集上的实际结果，不表示线上真实 LLM 性能。完整机器可读指标和
retrieval ablation 分别保存在同目录的 JSON 文件中。
