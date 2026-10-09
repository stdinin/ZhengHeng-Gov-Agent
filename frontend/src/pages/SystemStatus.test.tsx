import { render, screen } from '@testing-library/react'

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
