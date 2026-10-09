import { Alert, Button, Form, Input, Typography } from 'antd'
import { useState } from 'react'

import { login } from '../api/client'

export function Login() {
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(values: { email: string; password: string }) {
    setError(null)
    try {
      const response = await login(values.email, values.password)
      sessionStorage.setItem('zhengheng_access_token', response.access_token)
      setMessage(`已以 ${response.user.email} 登录。`)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : '登录失败。')
    }
  }

  return (
    <div style={{ maxWidth: 420 }}>
      <Typography.Paragraph>本地开发账户只能用于演示，生产环境不得使用。</Typography.Paragraph>
      {message ? <Alert type="success" message={message} showIcon /> : null}
      {error ? <Alert type="error" message={error} showIcon /> : null}
      <Form layout="vertical" onFinish={submit} style={{ marginTop: 16 }}>
        <Form.Item label="邮箱" name="email" rules={[{ required: true, type: 'email' }]}>
          <Input autoComplete="email" />
        </Form.Item>
        <Form.Item label="密码" name="password" rules={[{ required: true }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Button htmlType="submit" type="primary">登录</Button>
      </Form>
    </div>
  )
}
