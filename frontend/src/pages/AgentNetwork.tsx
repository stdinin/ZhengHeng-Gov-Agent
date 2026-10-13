import { Alert, Button, Table } from 'antd'
import { useEffect, useState } from 'react'
import { fetchAgentNetwork } from '../api/client'
import { BlankState, HealthTag, LoadingState, LoginRequired, PageHeading } from '../components/Workspace'
import { useTask } from '../hooks/useTask'
import { department } from '../lib/presentation'
import { useSession } from '../Session'
import type { AgentNetworkResponse } from '../types/api'

export function AgentNetwork() {
  const { user } = useSession()
  const allowed = !!user && user.role !== 'USER'
  const { data: network, error, loading, run } = useTask<AgentNetworkResponse>()
  const [updated, setUpdated] = useState<string | null>(null)
  useEffect(() => { if (allowed) void run(fetchAgentNetwork, () => setUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false }))) }, [allowed, run])
  const refresh = () => void run(fetchAgentNetwork, () => setUpdated(new Date().toLocaleTimeString('zh-CN', { hour12: false })))
  return <>
    <PageHeading title="协同部门" description="查看已配置的部门服务及最近一次处理情况。" extra={<Button onClick={refresh} loading={loading} disabled={!allowed}>刷新状态</Button>} />
    {!user ? <LoginRequired /> : !allowed ? <Alert type="warning" showIcon title="需要管理员权限" description="协同部门运行信息仅向部门管理员及系统管理员开放。" /> : <section className="panel" aria-busy={loading}><div className="panel-header"><h2>部门运行情况</h2><span className="muted">{network && updated ? '本次读取时间 ' + updated : '状态以本次探测为准'}</span></div>
      {loading ? <LoadingState label="正在检查部门服务…" /> : error ? <div className="panel-body"><Alert type="error" showIcon title="部门状态读取失败" description={error} action={<Button onClick={refresh}>重试</Button>} /></div> : network ? <div className="panel-body">
        <div className="status-overview"><div><span>统一受理服务</span><HealthTag value={network.orchestrator_health} /></div><div><span>语义处理服务</span><HealthTag value={network.pi_runtime_health} /></div></div>
        <div className="table-wrap"><Table rowKey="agent_id" pagination={false} dataSource={network.members} scroll={{ x: 720 }} locale={{ emptyText: '尚未配置协同部门，请联系管理员。' }} columns={[
          { title: '承办部门', dataIndex: 'dept_id', render: (v: string) => <strong>{department(v)}</strong> },
          { title: '服务状态', dataIndex: 'health', render: (v: string) => <HealthTag value={v} /> },
          { title: '最近耗时（毫秒）', dataIndex: 'recent_latency_ms', align: 'right', render: (v: number | null) => v === null ? '暂无记录' : v.toFixed(1) },
          { title: '超时次数', dataIndex: 'timeout_count', align: 'right' },
          { title: '最近办理记录', dataIndex: 'latest_child_trace_id', render: (v: string | null) => v ? <a href={'#/trace?id=' + encodeURIComponent(v)}>查看记录 →</a> : <span className="muted">暂无记录</span> },
        ]} /></div><p className="field-note" style={{ margin: '18px 0 0' }}>耗时和超时次数来自最近的已保存记录。服务未配置或不可用时，请联系运行维护人员。</p>
      </div> : <BlankState title="暂无部门信息" description="点击刷新，读取当前部门服务状态。" />}
    </section>}
  </>
}
