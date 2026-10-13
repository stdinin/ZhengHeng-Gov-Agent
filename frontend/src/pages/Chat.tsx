import { Alert, Button, Form, Input, Tag } from 'antd'
import { useRef, useState } from 'react'
import { sendChat } from '../api/client'
import { BlankState, LoadingState, LoginRequired, PageHeading } from '../components/Workspace'
import { useTask } from '../hooks/useTask'
import { department, safeSourceUrl } from '../lib/presentation'
import { useSession } from '../Session'
import type { ChatResponse } from '../types/api'

export function Chat() {
  const { user } = useSession()
  const [form] = Form.useForm()
  const task = useTask<ChatResponse>()
  const [submitted, setSubmitted] = useState('')
  const [cancelled, setCancelled] = useState(false)
  const sessionId = useRef<string | undefined>(undefined)
  const result = task.data
  function submit(values: { query: string }) {
    if (!user || task.loading) return
    setCancelled(false); setSubmitted(values.query.trim())
    void task.run(signal => sendChat(values.query, sessionId.current, signal), value => { sessionId.current = value.session_id })
  }
  function restart() { task.reset(); sessionId.current = undefined; form.resetFields(); setSubmitted(''); setCancelled(false) }
  return <>
    <PageHeading title="政策咨询" description="填写具体事项，查询相关政策及适用依据。" extra={<Button onClick={restart} disabled={task.loading}>新建咨询</Button>} />
    <div className="consult-layout"><div>
      <section className="panel" aria-labelledby="query-title">
        <div className="panel-header"><h2 id="query-title"><span className="section-index">01</span>咨询事项</h2><span className="muted">请勿填写身份证号等个人敏感信息</span></div>
        <div className="panel-body">
          {!user && <LoginRequired />}
          <Form form={form} layout="vertical" onFinish={submit} className="query-form" disabled={task.loading}>
            <Form.Item label="事项描述" name="query" rules={[{ required: true, whitespace: true, message: '请输入具体咨询事项。' }, { max: 4000, message: '咨询事项不能超过 4000 字。' }]}>
              <Input.TextArea rows={5} maxLength={4000} showCount placeholder="请说明涉及的地区、时间和办理事项。例如：申请住房补贴需要满足哪些条件，应准备哪些材料？" />
            </Form.Item>
            <div className="form-actions"><Button type="primary" htmlType="submit" loading={task.loading} disabled={!user}>提交咨询</Button>{task.loading && <Button disabled={false} onClick={() => { task.cancel(); setCancelled(true) }}>取消等待</Button>}<span className="field-note">答复将同时列出可核对的政策来源</span></div>
          </Form>
        </div>
      </section>
      <section className="panel" aria-labelledby="answer-title" aria-busy={task.loading}>
        <div className="panel-header"><h2 id="answer-title"><span className="section-index">02</span>办理答复</h2>{result && <Tag color={result.status === 'SUCCESS' ? 'success' : 'warning'}>{result.status === 'SUCCESS' ? '已答复' : '依据不足'}</Tag>}</div>
        {task.loading ? <LoadingState label="正在检索政策并核对依据，请稍候…" /> : task.error ? <div className="panel-body"><Alert type="error" showIcon title="本次咨询未完成" description={task.error} action={<Button onClick={() => void form.submit()}>重试</Button>} /></div> : result ? <div className="panel-body">
          <div className="answer-question"><strong>咨询事项：</strong>{submitted}</div>
          {result.orchestration?.partial && <Alert type="warning" showIcon title="部分部门未完成处理" description={'本次仅展示已完成的答复。未完成部门：' + result.orchestration.failed_departments.map(d => department(d.dept_id)).join('、')} />}
          {result.status === 'ABSTAIN' && <Alert type="warning" showIcon title="当前政策依据不足" description="请补充地区、办理时间或政策名称后再次查询，也可向相关主管部门咨询。" />}
          <div className="answer-text">{result.answer}</div>
          {result.warnings.length > 0 && <details className="muted"><summary>查看本次处理提示（{result.warnings.length}）</summary><ul>{result.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details>}
          <div className="answer-meta"><span>办理编号：<span className="mono">{result.trace_id}</span></span><a href={'#/trace?id=' + encodeURIComponent(result.trace_id)}>查看办理记录 →</a></div>
        </div> : <BlankState title={cancelled ? '已取消等待' : '暂无办理答复'} description={cancelled ? '本次等待已取消，后台处理可能仍在进行。可修改事项后重新提交。' : '提交咨询后，在此查看答复内容及处理结果。'} />}
      </section>
      {result && <section className="panel" aria-labelledby="citation-title"><div className="panel-header"><h2 id="citation-title"><span className="section-index">03</span>政策依据</h2><span className="muted">共 {result.citations.length} 条引用</span></div><div className="panel-body">{result.citations.length ? <ol className="citation-list">{result.citations.map((citation, index) => {
        const url = safeSourceUrl(citation.source_url)
        return <li key={citation.id + '-' + index}><div className="citation-title"><span className="citation-number">{citation.id}</span><strong>{citation.title}</strong></div><div className="citation-meta"><span>{department(citation.department)}</span>{citation.document_number && <span>{citation.document_number}</span>}{citation.written_date && <span>成文日期：{citation.written_date}</span>}<span>{citation.status === 'ACTIVE' ? '当前有效版本' : '状态待核对'}</span></div><p className="citation-excerpt">{citation.excerpt}</p>{url && <a className="citation-link" href={url} target="_blank" rel="noopener noreferrer">查看政策原文 ↗</a>}</li>
      })}</ol> : <BlankState title="暂无可引用的政策" description="可补充政策名称或适用范围后重新查询。" />}</div></section>}
    </div><aside className="consult-sidebar" aria-label="咨询指引">
      <section className="panel side-panel"><div className="panel-body"><h3>咨询填写指引</h3><ol className="guidance-list"><li>明确办理事项，尽量一次咨询一个问题。</li><li>补充适用地区、时间和主体类型。</li><li>已有政策名称或文号的，可一并填写。</li></ol><a className="guidance-link" href="#/trace">查询办理记录 →</a></div></section>
      <section className="panel"><div className="panel-body"><h3>协同业务范围</h3><ul className="department-list"><li>税务业务<span>税费与优惠</span></li><li>人社业务<span>就业与社保</span></li><li>住建业务<span>住房与建设</span></li></ul><p className="field-note" style={{ margin: '18px 0 0' }}>部门可用情况以系统实际配置为准。</p><a className="guidance-link" href="#/agents">查看协同部门 →</a></div></section>
    </aside></div>
  </>
}
