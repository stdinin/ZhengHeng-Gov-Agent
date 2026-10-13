import { Alert, Button, Descriptions, Form, Input, Table, Tag } from 'antd'
import { useEffect } from 'react'
import { fetchTrace } from '../api/client'
import { BlankState, LoadingState, LoginRequired, PageHeading } from '../components/Workspace'
import { useTask } from '../hooks/useTask'
import { dateTime, department } from '../lib/presentation'
import { useSession } from '../Session'
import type { TracePayload } from '../types/api'

const nodeNames: Record<string, string> = {
  Intent: '意图识别', Rewrite: '问题改写', Route: '部门路由', Retrieve: '政策检索',
  Answer: '生成答复', Verify: '答复核验', DepartmentRetrieve: '部门检索',
  DepartmentAnswer: '部门答复', DepartmentVerify: '部门核验', Aggregate: '结果汇总',
  GlobalVerify: '全局核验', Dispatch: '部门调度',
}
export function TraceExplorer({ initialId = '' }: { initialId?: string }) {
  const { user } = useSession()
  const [form] = Form.useForm()
  const { data: trace, loading, error, run, cancel } = useTask<TracePayload>()
  useEffect(() => {
    if (initialId && user) {
      form.setFieldsValue({ traceId: initialId })
      void run(signal => fetchTrace(initialId, signal))
    }
  }, [initialId, user, form, run])
  function submit(values: { traceId: string }) {
    if (!loading && user) void run(signal => fetchTrace(values.traceId, signal))
  }
  return <>
    <PageHeading title="办理记录" description="输入办理编号，核对咨询内容、部门处理情况和各环节记录。" />
    <section className="panel"><div className="panel-header"><h2>记录查询</h2><span className="muted">编号可在咨询答复下方获取</span></div><div className="panel-body">
      {!user && <LoginRequired />}
      <Form form={form} className="query-bar" onFinish={submit}>
        <Form.Item name="traceId" rules={[{ required: true, whitespace: true, message: '请输入办理编号。' }, { max: 128, message: '办理编号过长，请检查。' }]}><Input aria-label="办理编号" placeholder="请输入完整办理编号" allowClear disabled={loading || !user} /></Form.Item>
        <Button type="primary" htmlType="submit" loading={loading} disabled={!user}>查询记录</Button>{loading && <Button onClick={cancel}>取消</Button>}
      </Form>
    </div></section>
    <section className="panel" aria-busy={loading}><div className="panel-header"><h2>办理详情</h2>{trace && <Tag color={trace.status === 'SUCCESS' ? 'success' : 'warning'}>{trace.status === 'SUCCESS' ? '已完成' : '依据不足'}</Tag>}</div>
      {loading ? <LoadingState /> : error ? <div className="panel-body"><Alert type="error" showIcon title="记录查询未完成" description={error} action={<Button onClick={() => void form.submit()}>重试</Button>} /></div> : trace ? <div className="panel-body">
        <h3 className="record-heading">{trace.query}</h3>
        <Descriptions bordered size="small" column={{ xs: 1, sm: 1, md: 2 }} className="record-details" items={[
          { key: 'id', label: '办理编号', children: <span className="mono">{trace.id}</span>, span: 2 },
          { key: 'date', label: '办理时间', children: dateTime(trace.created_at) },
          { key: 'type', label: '记录类型', children: trace.trace_kind === 'child' ? '部门处理记录' : '总办理记录' },
          { key: 'mode', label: '处理方式', children: ({ single_agent: '单部门处理', multi_agent: '多部门协同', department_agent: '部门内处理' } as Record<string, string>)[trace.execution_mode ?? 'single_agent'] ?? '其他' },
          { key: 'department', label: '承办部门', children: trace.dept_id ? department(trace.dept_id) : '统一受理' },
          { key: 'partial', label: '是否部分完成', children: trace.partial ? '是' : '否' },
          { key: 'parent', label: '上级记录', children: trace.parent_trace_id ? <a className="mono" href={'#/trace?id=' + encodeURIComponent(trace.parent_trace_id)}>{trace.parent_trace_id}</a> : '—' },
          { key: 'children', label: '部门记录', span: 2, children: trace.child_trace_ids?.length ? <div className="record-links">{trace.child_trace_ids.map(id => <a className="mono" key={id} href={'#/trace?id=' + encodeURIComponent(id)}>{id}</a>)}</div> : '—' },
        ]} />
        <h3 className="record-heading">处理环节</h3>
        <div className="table-wrap"><Table size="middle" pagination={false} rowKey="key" dataSource={trace.nodes.map((node, index) => ({ ...node, key: index }))} locale={{ emptyText: '本次记录没有环节明细' }} columns={[
          { title: '环节', dataIndex: 'node', render: (v: string) => nodeNames[v] ?? v },
          { title: '耗时（毫秒）', dataIndex: 'latency_ms', align: 'right', render: (v: number) => v.toFixed(1) },
          { title: '降级处理', dataIndex: 'fallback', render: (v: boolean) => <Tag color={v ? 'warning' : 'default'}>{v ? '是' : '否'}</Tag> },
        ]} /></div>
        {trace.answer && <><h3 className="record-heading" style={{ marginTop: 26 }}>答复内容</h3><div className="answer-text">{trace.answer}</div></>}
      </div> : <BlankState title="尚未查询办理记录" description="请输入编号，或从咨询答复、协同部门页面进入。" />}
    </section>
  </>
}
