import { Alert, Card, Descriptions, Typography } from 'antd'

export function AdminWorkspace() {
  return (
    <Card title="管理与评测">
      <Typography.Paragraph>
        此处只显示已经落盘的 Eval Run 与 Trace 数据。当前前端不会预填 Recall、MRR、成功率或性能数据。
      </Typography.Paragraph>
      <Alert
        type="info"
        showIcon
        message="尚未加载真实评测产物"
        description="请在真实基础设施恢复后运行冻结 Eval Set；生成的 runs/<run_id>/metrics.json 才可作为仪表盘数据源。"
      />
      <Descriptions bordered column={1} size="small" style={{ marginTop: 16 }}>
        <Descriptions.Item label="策略灰度">基于稳定分桶与 Replay Gate；未通过真实回放的候选不能上线。</Descriptions.Item>
        <Descriptions.Item label="回滚">只在样本量和劣化阈值满足后记录决策；不删除历史版本。</Descriptions.Item>
      </Descriptions>
    </Card>
  )
}
