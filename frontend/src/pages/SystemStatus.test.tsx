import { fireEvent, render, screen } from '@testing-library/react'

import { SystemStatus } from './SystemStatus'

it('shows an unavailable dependency as not ready', async () => {
  render(
    <SystemStatus
      loadStatus={async () => ({
        status: 'unready',
        dependencies: {
          mongo: { name: 'mongo', ready: false, latency_ms: 1, error: 'not reachable' },
        },
      })}
    />,
  )

  expect((await screen.findAllByText('未就绪')).length).toBeGreaterThan(0)
  expect(screen.getByText('mongo')).toBeInTheDocument()
})

it('never reports an empty dependency list as healthy', async () => {
  render(<SystemStatus loadStatus={async () => ({ status: 'ready', dependencies: {} })} />)
  expect(await screen.findByText('系统未就绪')).toBeInTheDocument()
  expect(screen.queryByText('系统已就绪')).not.toBeInTheDocument()
})

it('allows recovery after a failed status request', async () => {
  const load = vi.fn().mockRejectedValueOnce(new Error('无法连接服务')).mockResolvedValueOnce({
    status: 'ready', dependencies: { mongo: { name: 'mongo', ready: true, latency_ms: 2 } },
  })
  render(<SystemStatus loadStatus={load} />)
  expect(await screen.findByText('状态检查失败')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  expect(await screen.findByText('系统已就绪')).toBeInTheDocument()
  expect(screen.queryByText('状态检查失败')).not.toBeInTheDocument()
})
