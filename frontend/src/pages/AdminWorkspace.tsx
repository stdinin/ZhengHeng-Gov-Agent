import { Descriptions, Tag } from 'antd'
import { BlankState, PageHeading } from '../components/Workspace'

export function AdminWorkspace() {
  return <>
    <PageHeading title="评测管理" description="查看评测接入情况和策略发布要求。" />
    <section className="panel"><div className="panel-header"><h2>评测结果</h2><Tag>尚未接入</Tag></div><BlankState title="暂无可展示的评测结果" description="当前页面尚未接入评测报告。请联系管理员获取已完成的评测记录。" /></section>
    <section className="panel"><div className="panel-header"><h2>策略发布要求</h2><span className="muted">管理说明</span></div><div className="panel-body">
      <p className="management-note">策略审核和发布目前通过管理接口完成。以下为办理要求，当前页面不提供发布操作。</p>
      <Descriptions bordered size="small" column={1} items={[
        { key: 'review', label: '回放核验', children: '候选策略须使用已保存的办理记录进行回放，并通过发布检查。' },
        { key: 'gray', label: '灰度发布', children: '核验通过后，由管理员批准发布比例并记录审批信息。' },
        { key: 'rollback', label: '晋升与回滚', children: '依据运行记录及评测结果决定是否扩大使用范围；发生问题时保留历史版本并回滚。' },
      ]} />
    </div></section>
  </>
}
