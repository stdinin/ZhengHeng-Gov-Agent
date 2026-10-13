import { Alert, Button, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { LoadingState, PageBoundary } from './components/Workspace'
import { navigate, roleName } from './lib/presentation'
import { SessionProvider, useSession } from './Session'
import './styles.css'

const Chat = lazy(() => import('./pages/Chat').then(m => ({ default: m.Chat })))
const TraceExplorer = lazy(() => import('./pages/TraceExplorer').then(m => ({ default: m.TraceExplorer })))
const AgentNetwork = lazy(() => import('./pages/AgentNetwork').then(m => ({ default: m.AgentNetwork })))
const SystemStatus = lazy(() => import('./pages/SystemStatus').then(m => ({ default: m.SystemStatus })))
const AdminWorkspace = lazy(() => import('./pages/AdminWorkspace').then(m => ({ default: m.AdminWorkspace })))
const Login = lazy(() => import('./pages/Login').then(m => ({ default: m.Login })))
const pages = [
  { key: 'chat', title: '政策咨询', icon: 'document', group: '业务办理' },
  { key: 'trace', title: '办理记录', icon: 'list', group: '业务办理' },
  { key: 'agents', title: '协同部门', icon: 'building', group: '运行管理' },
  { key: 'admin', title: '评测管理', icon: 'folder', group: '运行管理' },
  { key: 'status', title: '系统状态', icon: 'status', group: '运行管理' },
]
function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    document: 'M7 3h7l4 4v14H7z M14 3v5h4 M10 12h5 M10 16h5',
    list: 'M5 4h14v17H5z M8 8h8 M8 12h8 M8 16h5',
    building: 'M3 21h18 M5 21V9h14v12 M3 9l9-6 9 6 M8 12v5 M12 12v5 M16 12v5',
    folder: 'M3 7V4h6l3 3h9v13H3z M7 12h10 M7 16h7',
    status: 'M3 12h4l3-7 4 14 3-7h4',
  }
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.document} /></svg>
}
function route() {
  const [raw, query = ''] = window.location.hash.replace(/^#\/?/, '').split('?')
  return { page: pages.some(p => p.key === raw) || raw === 'login' ? raw : 'chat', id: new URLSearchParams(query).get('id') ?? '' }
}
function Workspace() {
  const [current, setCurrent] = useState(route)
  const [menuOpen, setMenuOpen] = useState(false)
  const main = useRef<HTMLElement>(null)
  const { user, checking, notice, signOut } = useSession()
  useEffect(() => {
    function change() { setCurrent(route()); setMenuOpen(false); main.current?.focus() }
    function escape(event: KeyboardEvent) { if (event.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('hashchange', change)
    window.addEventListener('keydown', escape)
    return () => { window.removeEventListener('hashchange', change); window.removeEventListener('keydown', escape) }
  }, [])
  const title = current.page === 'login' ? '账户登录' : pages.find(p => p.key === current.page)!.title
  useEffect(() => { document.title = title + ' · 政衡政策咨询工作台' }, [title])
  const views: Record<string, ReactNode> = { chat: <Chat />, trace: <TraceExplorer initialId={current.id} />, agents: <AgentNetwork />, admin: <AdminWorkspace />, status: <SystemStatus />, login: <Login /> }
  return <div className="app-shell">
    <a className="skip-link" href="#workspace-main" onClick={event => { event.preventDefault(); main.current?.focus() }}>跳至主要内容</a>
    <header className="app-header">
      <button className="mobile-menu" aria-label="切换导航菜单" aria-expanded={menuOpen} aria-controls="main-navigation" onClick={() => setMenuOpen(!menuOpen)}>☰</button>
      <a href="#/chat" className="brand"><span className="brand-mark"><Icon name="building" /></span><strong>政衡</strong><span className="brand-divider" /><span className="brand-name">政策咨询工作台</span></a>
      <div className="account-area">{checking ? <span>正在确认登录状态</span> : user ? <><span className="account-email" title={user.email}>{user.email}</span><span className="account-role">{roleName(user.role)}</span><button onClick={() => { signOut(); navigate('login') }}>退出登录</button></> : <button onClick={() => navigate('login')}>账户登录</button>}</div>
    </header>
    <div className="workspace-layout">
      {menuOpen && <button className="nav-backdrop" aria-label="关闭导航菜单" onClick={() => setMenuOpen(false)} />}
      <aside className={'sidebar' + (menuOpen ? ' is-open' : '')}>
        <nav id="main-navigation" aria-label="主导航">{['业务办理', '运行管理'].map(group => <div className="nav-group" key={group}><div className="nav-label">{group}</div>{pages.filter(p => p.group === group).map(page => <a key={page.key} href={'#/' + page.key} className={current.page === page.key ? 'nav-item is-active' : 'nav-item'} aria-current={current.page === page.key ? 'page' : undefined} onClick={() => setMenuOpen(false)}><Icon name={page.icon} /><span>{page.title}</span></a>)}</div>)}</nav>
        <div className="sidebar-note"><strong>使用提示</strong><p>请描述具体事项，并核对答复中的政策原文及适用范围。</p></div>
      </aside>
      <main id="workspace-main" className="workspace-main" tabIndex={-1} ref={main}>
        <div className="breadcrumb">工作台<span>/</span>{title}</div>
        {notice && <Alert className="session-notice" type="warning" title={notice} showIcon action={current.page !== 'login' ? <Button size="small" onClick={() => navigate('login')}>前往登录</Button> : undefined} />}
        <PageBoundary key={current.page + current.id + (user?.id ?? 'guest')}><Suspense fallback={<LoadingState label="正在加载页面…" />}><div className="page-content">{checking ? <LoadingState label="正在确认登录状态…" /> : views[current.page]}</div></Suspense></PageBoundary>
        <footer className="workspace-footer"><span>政衡 · 政策咨询与协同办理</span><span>政策信息以原文及主管部门解释为准</span></footer>
      </main>
    </div>
  </div>
}
export function App() {
  return <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#245980', colorInfo: '#245980', colorInfoBg: '#f0f5f9', colorInfoBorder: '#d2e0ea', colorSuccess: '#3f735e', colorSuccessBg: '#f0f7f3', colorSuccessBorder: '#d4e5db', colorWarning: '#a57526', colorWarningBg: '#fff9ed', colorWarningBorder: '#eddfbf', colorError: '#ac4040', colorErrorBg: '#fff3f2', colorErrorBorder: '#edcfcc', colorText: '#263544', colorTextSecondary: '#657482', colorBorder: '#d9e0e6', colorBgLayout: '#f3f5f7', borderRadius: 4, fontSize: 14, controlHeight: 36, fontFamily: '"Microsoft YaHei", "PingFang SC", -apple-system, BlinkMacSystemFont, sans-serif', motion: false }, components: { Button: { primaryShadow: 'none' }, Table: { headerBg: '#f5f7f9', headerColor: '#526372' } } }}><SessionProvider><Workspace /></SessionProvider></ConfigProvider>
}
