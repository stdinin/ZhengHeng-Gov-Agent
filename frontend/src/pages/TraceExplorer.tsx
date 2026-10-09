import { Alert, Button, Card, Form, Input, Table, Typography } from 'antd'
import { useState } from 'react'

import { fetchTrace } from '../api/client'
import type { TracePayload } from '../types/api'

export function TraceExplorer() {
  const [trace, setTrace] = useState<TracePayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(values: { traceId: string }) {
    setError(null)
    try {
      setTrace(await fetchTrace(values.traceId))
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : '无法读取 Trace。')
    }
  }

  return (
    <Card title="Trace Explorer">
      <Typography.Paragraph>按 Trace ID 查看本次固定 DAG 的实际节点记录。</Typography.Paragraph>
      <Form layout="inline" onFinish={submit}>
        <Form.Item name="traceId" rules={[{ required: true, message: '请输入 Trace ID。' }]}>
          <Input placeholder="trace_uuid" aria-label="Trace ID" />
        </Form.Item>
        <Button htmlType="submit">查询</Button>
      </Form>
      {error ? <Alert style={{ marginTop: 16 }} type="error" message={error} showIcon /> : null}
      {trace ? (
        <>
          <Typography.Paragraph style={{ marginTop: 20 }}>问题：{trace.query}</Typography.Paragraph>
          <Table
            rowKey="node"
            pagination={false}
            dataSource={trace.nodes}
            columns={[
              { title: '节点', dataIndex: 'node' },
              { title: '耗时 (ms)', dataIndex: 'latency_ms' },
              { title: 'Fallback', dataIndex: 'fallback', render: (value: boolean) => (value ? '是' : '否') },
            ]}
          />
        </>
      ) : null}
    </Card>
  )
}
