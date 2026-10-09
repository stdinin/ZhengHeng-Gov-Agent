import { Layout, Tabs, Typography } from 'antd'
import { lazy, Suspense } from 'react'

const Login = lazy(async () => ({ default: (await import('./pages/Login')).Login }))
const SystemStatus = lazy(async () => ({ default: (await import('./pages/SystemStatus')).SystemStatus }))
const Chat = lazy(async () => ({ default: (await import('./pages/Chat')).Chat }))
const TraceExplorer = lazy(async () => ({ default: (await import('./pages/TraceExplorer')).TraceExplorer }))
const AdminWorkspace = lazy(async () => ({ default: (await import('./pages/AdminWorkspace')).AdminWorkspace }))

export function App() {
  return (
    <Layout style={{ minHeight: '100vh', padding: 32 }}>
      <Layout.Content style={{ maxWidth: 960, margin: '0 auto', width: '100%' }}>
        <Typography.Title level={1}>政衡 Agent</Typography.Title>
        <Typography.Paragraph>
          基于受控 Harness 的多部门可信政务 RAG 系统；每一条事实结论都应回到当前有效政策证据。
        </Typography.Paragraph>
        <Suspense fallback="加载页面中…">
          <Tabs
            items={[
              { key: 'chat', label: '政策问答', children: <Chat /> },
              { key: 'trace', label: 'Trace', children: <TraceExplorer /> },
              { key: 'admin', label: '管理与评测', children: <AdminWorkspace /> },
              { key: 'status', label: '系统状态', children: <SystemStatus /> },
              { key: 'login', label: '登录', children: <Login /> },
            ]}
          />
        </Suspense>
      </Layout.Content>
    </Layout>
  )
}
