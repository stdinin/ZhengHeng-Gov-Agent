import { Alert, Card, Descriptions, Spin, Tag } from 'antd'
import { useEffect, useState } from 'react'

import { fetchReadiness } from '../api/client'
import type { ReadinessPayload } from '../types/api'

type SystemStatusProps = {
  loadStatus?: () => Promise<ReadinessPayload>
}

export function SystemStatus({ loadStatus = fetchReadiness }: SystemStatusProps) {
  const [status, setStatus] = useState<ReadinessPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void loadStatus().then(setStatus).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : '无法读取系统状态。')
    })
  }, [loadStatus])

  if (error) {
    return <Alert type="error" message="状态检查失败" description={error} showIcon />
  }
  if (!status) {
    return <Spin aria-label="加载系统状态" />
  }

  const allReady = Object.values(status.dependencies).every((dependency) => dependency.ready)
  return (
    <Card title="基础设施状态" extra={<Tag color={allReady ? 'green' : 'red'}>{allReady ? '就绪' : '未就绪'}</Tag>}>
      <p>此页面显示后端对真实依赖的探测结果；不会把不可用服务显示为正常。</p>
      <Descriptions bordered column={1} size="small">
        {Object.values(status.dependencies).map((dependency) => (
          <Descriptions.Item key={dependency.name} label={dependency.name}>
            <Tag color={dependency.ready ? 'green' : 'red'}>{dependency.ready ? '就绪' : '未就绪'}</Tag>
            <span>{` ${dependency.latency_ms} ms`}</span>
            {dependency.error ? <span>{` — ${dependency.error}`}</span> : null}
          </Descriptions.Item>
        ))}
      </Descriptions>
    </Card>
  )
}
