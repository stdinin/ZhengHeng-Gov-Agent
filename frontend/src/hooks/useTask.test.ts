import { act, renderHook } from '@testing-library/react'
import { useTask } from './useTask'

it('ignores a superseded response even if its transport does not respect abort', async () => {
  const { result } = renderHook(() => useTask<string>())
  let oldResolve!: (value: string) => void
  let old!: Promise<void>
  act(() => { old = result.current.run(() => new Promise(resolve => { oldResolve = resolve })) })
  await act(async () => { await result.current.run(async () => 'new result') })
  await act(async () => { oldResolve('stale result'); await old })
  expect(result.current.data).toBe('new result')
})
it('does not publish a cancelled result or execute its side effects', async () => {
  const { result } = renderHook(() => useTask<string>())
  let resolve!: (value: string) => void
  const onSuccess = vi.fn()
  let promise!: Promise<void>
  act(() => { promise = result.current.run(() => new Promise(done => { resolve = done }), onSuccess) })
  act(() => result.current.cancel())
  await act(async () => { resolve('late'); await promise })
  expect(result.current.data).toBeNull()
  expect(result.current.loading).toBe(false)
  expect(onSuccess).not.toHaveBeenCalled()
})
