import { Alert, Button, Card, Form, Input, List, Space, Tag, Typography } from 'antd'
import { useState } from 'react'

import { sendChat } from '../api/client'
import type { ChatResponse } from '../types/api'

export function Chat() {
  const [result, setResult] = useState<ChatResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(values: { query: string }) {
    setLoading(true)
    setError(null)
    try {
      setResult(await sendChat(values.query, result?.session_id))
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : '政策问答暂时不可用。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ display: 'flex' }}>
      <Card title="政策问答" extra={<Tag color="blue">证据优先</Tag>}>
        <Typography.Paragraph>
          回答只应基于当前有效政策文件。基础设施不可用时，系统会明确提示，不会生成替代性结论。
        </Typography.Paragraph>
        <Form layout="vertical" onFinish={submit}>
          <Form.Item label="你的问题" name="query" rules={[{ required: true, message: '请输入问题。' }]}>
            <Input.TextArea rows={4} maxLength={4000} placeholder="例如：增值税优惠的适用条件是什么？" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>发送问题</Button>
        </Form>
      </Card>
      {error ? <Alert type="error" message="问答未完成" description={error} showIcon /> : null}
      {result ? (
        <Card title="回答" extra={<Tag color={result.status === 'SUCCESS' ? 'green' : 'orange'}>{result.status}</Tag>}>
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{result.answer}</Typography.Paragraph>
          <Typography.Text type="secondary">Trace: {result.trace_id} · 尝试次数: {result.attempts}</Typography.Text>
          {result.warnings.length > 0 ? <Alert type="warning" message={result.warnings.join('；')} showIcon /> : null}
          <List
            style={{ marginTop: 20 }}
            header="引用来源"
            dataSource={result.citations}
            locale={{ emptyText: '本次没有可用的事实引用。' }}
            renderItem={(citation) => (
              <List.Item>
                <Space direction="vertical" size={0}>
                  <Typography.Text strong>[{citation.id}] {citation.title}</Typography.Text>
                  <Typography.Text type="secondary">{citation.department} · {citation.status}</Typography.Text>
                  <Typography.Text>{citation.excerpt}</Typography.Text>
                  {citation.source_url ? <a href={citation.source_url} target="_blank" rel="noreferrer">打开原文</a> : null}
                </Space>
              </List.Item>
            )}
          />
        </Card>
      ) : null}
    </Space>
  )
}
