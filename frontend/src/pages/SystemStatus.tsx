import { Alert, Button, Table, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { fetchReadiness } from '../api/client'
import { BlankState, LoadingState, PageHeading } from '../components/Workspace'
import { useTask } from '../hooks/useTask'
import type { DependencyStatus, ReadinessPayload } from '../types/api'

type SystemStatusProps = { loadStatus?: (signal?: AbortSignal) => Promise<ReadinessPayload> }
const dependencyRoles: Record<string, string> = { mongo: '文档与办理记录', mongodb: '文档与办理记录', redis: '会话与临时状态', opensearch: '政策全文检索', milvus: '政策语义检索' }
export function SystemStatus({ loadStatus = fetchReadiness }: SystemStatusProps) {
  const { data: status, error, loading, run } = useTask<ReadinessPayload>()
  const [updated, setUpdated] = useState<string | null>(null)
  useEffect(() => { void run(loadStatus, () => setUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false }))) }, [loadStatus, run])
  const refresh = () => void run(loadStatus, () => setUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false })))
  const dependencies = status ? Object.values(status.dependencies) : []
  const allReady = status?.status === 'ready' && dependencies.length > 0 && dependencies.every(d => d.ready)
  return <>
    <PageHeading title="系统状态" description="查看支撑政策咨询的数据与检索服务是否可用。" extra={<Button onClick={refresh} loading={loading}>重新检查</Button>} />
    <section className="panel" aria-busy={loading}><div className="panel-header"><h2>服务检查结果</h2><span className="muted">{status && updated ? '本次读取时间 ' + updated : '按需检查'}</span></div>
      {loading ? <LoadingState label="正在检查系统状态…" /> : error ? <div className="panel-body"><Alert type="error" title="状态检查失败" description={error} showIcon action={<Button onClick={refresh}>重试</Button>} /></div> : status ? <div className="panel-body">
        <Alert type={allReady ? 'success' : 'warning'} showIcon title={allReady ? '系统已就绪' : '系统未就绪'} description={allReady ? '本次检查中，各项依赖均可正常连接。' : dependencies.length ? '部分服务未就绪或后端尚未就绪，政策咨询可能暂时无法完成。' : '未获得依赖检查结果，暂时无法确认系统可用。'} />
        {dependencies.length ? <div className="table-wrap"><Table rowKey="name" pagination={false} dataSource={dependencies} scroll={{ x: 540 }} columns={[
          { title: '服务名称', dataIndex: 'name', render: (value: string) => <><strong>{value}</strong><div className="muted">{dependencyRoles[value.toLowerCase()] ?? '基础服务'}</div></> },
          { title: '检查状态', dataIndex: 'ready', render: (v: boolean) => <Tag color={v ? 'success' : 'error'}>{v ? '就绪' : '未就绪'}</Tag> },
          { title: '响应时间', dataIndex: 'latency_ms', render: (v: number) => v.toFixed(1) + ' ms' },
          { title: '说明', render: (_: unknown, d: DependencyStatus) => d.error ? <details className="error-details"><summary>查看异常详情</summary><pre>{d.error}</pre></details> : d.ready ? '连接正常' : '请重新检查或联系管理员' },
        ]} /></div> : <BlankState title="暂无依赖数据" description="请稍后重新检查，或联系管理员确认服务配置。" />}
      </div> : null}
    </section>
  </>
}
