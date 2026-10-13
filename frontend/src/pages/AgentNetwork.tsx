import { Alert, Button, Card, Descriptions, Table, Typography } from 'antd'
import { useState } from 'react'

import { fetchAgentNetwork } from '../api/client'
import type { AgentNetworkResponse } from '../types/api'

export function AgentNetwork() {
  const [network, setNetwork] = useState<AgentNetworkResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setError(null)
    try {
      setNetwork(await fetchAgentNetwork())
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : '无法读取 Agent Network。')
    }
  }

  return (
    <Card title="Agent Network" extra={<Button onClick={load}>刷新</Button>}>
      <Typography.Paragraph>
        仅展示静态注册服务与实际 Trace 汇总的运行状态；不展示 query、用户信息或原始文档内容。
      </Typography.Paragraph>
      {error ? <Alert type="error" showIcon message={error} /> : null}
      {!network && !error ? (
        <Alert type="info" showIcon message="尚未加载实时 Agent Network 状态。" />
      ) : null}
      {network ? (
        <>
          <Descriptions bordered size="small" column={1} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="Orchestrator">{network.orchestrator_health}</Descriptions.Item>
            <Descriptions.Item label="Pi Runtime">{network.pi_runtime_health}</Descriptions.Item>
          </Descriptions>
          <Table
            rowKey="agent_id"
            pagination={false}
            dataSource={network.members}
            columns={[
              { title: 'Agent', dataIndex: 'agent_id' },
              { title: 'Department', dataIndex: 'dept_id' },
              { title: 'Health', dataIndex: 'health' },
              { title: 'Runtime', dataIndex: 'runtime_backend' },
              {
                title: 'Recent latency (ms)',
                dataIndex: 'recent_latency_ms',
                render: (value: number | null) => value ?? '—',
              },
              { title: 'Timeouts', dataIndex: 'timeout_count' },
              {
                title: 'Latest child Trace',
                dataIndex: 'latest_child_trace_id',
                render: (value: string | null) =>
                  value ? <Typography.Link href={`#trace-${value}`}>{value}</Typography.Link> : '—',
              },
            ]}
          />
        </>
      ) : null}
    </Card>
  )
}
