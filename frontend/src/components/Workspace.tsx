import { Alert, Button, Empty, Spin, Tag } from 'antd'
import { Component, type ReactNode } from 'react'
import { navigate } from '../lib/presentation'

export function PageHeading({ title, description, extra }: { title: string; description: string; extra?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{extra}</div>
}
export function BlankState({ title, description }: { title: string; description: string }) {
  return <div className="blank-state"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<><strong>{title}</strong><p>{description}</p></>} /></div>
}
export function LoadingState({ label = '正在读取数据…' }: { label?: string }) {
  return <div role="status" className="loading-state"><Spin size="small" /><span>{label}</span></div>
}
export function LoginRequired() {
  return <Alert type="info" showIcon title="请先登录" description="登录后可查询政策、查看办理记录及账户权限内的业务。" action={<Button onClick={() => navigate('login')}>前往登录</Button>} />
}
export function HealthTag({ value }: { value: string }) {
  const states: Record<string, [string, string]> = { healthy: ['正常', 'success'], ready: ['正常', 'success'], unhealthy: ['异常', 'error'], unreachable: ['无法连接', 'error'], not_configured: ['未配置', 'default'], unknown: ['待确认', 'default'] }
  const [label, color] = states[value] ?? ['待确认', 'default']
  return <Tag color={color}>{label}</Tag>
}
export class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <div className="panel"><Alert type="error" showIcon title="页面暂时无法显示" description="请重新加载页面。如仍无法打开，请联系管理员。" action={<Button onClick={() => window.location.reload()}>重新加载</Button>} /></div>
    return this.props.children
  }
}
