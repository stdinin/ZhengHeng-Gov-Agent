import { Alert, Button, Form, Input } from 'antd'
import { login } from '../api/client'
import { PageHeading } from '../components/Workspace'
import { useTask } from '../hooks/useTask'
import { navigate, roleName } from '../lib/presentation'
import { useSession } from '../Session'
import type { LoginResponse } from '../types/api'

export function Login() {
  const { user, signIn, signOut } = useSession()
  const task = useTask<LoginResponse>()
  async function submit(values: { email: string; password: string }) {
    if (task.loading) return
    await task.run(signal => login(values.email.trim(), values.password, signal), result => { signIn(result); navigate('chat') })
  }
  return <>
    <PageHeading title="账户登录" description="使用分配的业务账户访问政策咨询及相关记录。" />
    <section className="panel login-panel"><div className="panel-body">
      <h2>{user ? '当前账户' : '登录工作台'}</h2>
      <p className="login-intro">{user ? '已登录，可继续办理业务或退出当前账户。' : '请输入账户邮箱与密码。账户权限由管理员分配。'}</p>
      {user ? <><div className="account-details"><div>{user.email}</div><div className="muted">{roleName(user.role)}</div></div><div className="form-actions"><Button type="primary" onClick={() => navigate('chat')}>进入政策咨询</Button><Button onClick={signOut}>退出登录</Button></div></> : <>
        {task.error && <Alert type="error" showIcon title="登录未完成" description={task.error} />}
        <Form layout="vertical" onFinish={submit} disabled={task.loading} requiredMark={false}>
          <Form.Item label="账户邮箱" name="email" rules={[{ required: true, whitespace: true, message: '请输入账户邮箱。' }, { type: 'email', message: '请输入有效的邮箱地址。' }]}><Input autoComplete="username" inputMode="email" placeholder="请输入账户邮箱" /></Form.Item>
          <Form.Item label="登录密码" name="password" rules={[{ required: true, message: '请输入登录密码。' }]}><Input.Password autoComplete="current-password" placeholder="请输入密码" /></Form.Item>
          <Button type="primary" htmlType="submit" loading={task.loading} block>登录</Button>
        </Form>
      </>}
      <div className="login-footer"><p>账户或权限问题请联系管理员。公共设备使用完毕后，请退出登录。</p></div>
    </div></section>
  </>
}
