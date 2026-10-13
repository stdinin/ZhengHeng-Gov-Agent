import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearToken, fetchAgentNetwork, fetchReadiness, fetchTrace, getToken, login, saveToken, sendChat, sessionEvent } from './client'

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
beforeEach(() => { clearToken() })
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); clearToken() })
describe('API failure boundaries', () => {
  it('handles non-JSON gateway errors without exposing parsing failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>gateway error</html>', { status: 502 })))
    await expect(fetchReadiness()).rejects.toThrow('服务暂时不可用')
  })
  it('rejects malformed successful responses before they reach a page', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ status: 'ready', dependencies: { mongo: { ready: true } } })))
    await expect(fetchReadiness()).rejects.toThrow('数据不完整')
  })
  it('retains individual failures from the actual 503 readiness contract', async () => {
    const dependencies = { mongo: { name: 'mongo', ready: false, latency_ms: 4, error: 'connection refused' } }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: { details: { dependencies } } }, 503)))
    expect(await fetchReadiness()).toEqual({ status: 'unready', dependencies })
  })
  it('does not dereference absent error details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: 'Unavailable' }, 503)))
    await expect(fetchReadiness()).rejects.toThrow('服务暂时不可用')
  })
  it('expires an authenticated session on 401', async () => {
    saveToken('test-old-token')
    const listener = vi.fn()
    window.addEventListener(sessionEvent, listener)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({}, 401)))
    await expect(fetchTrace('test-record')).rejects.toThrow('登录已失效')
    expect(getToken()).toBeNull()
    expect(listener).toHaveBeenCalledOnce()
    window.removeEventListener(sessionEvent, listener)
  })
  it('does not let a late 401 clear a newer login', async () => {
    saveToken('test-old-token')
    let finish!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    const request = fetchTrace('record')
    saveToken('test-new-token')
    finish(response({}, 401))
    await expect(request).rejects.toThrow('登录已失效')
    expect(getToken()).toBe('test-new-token')
  })
  it('keeps a valid session on insufficient permissions', async () => {
    saveToken('test-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({}, 403)))
    await expect(fetchAgentNetwork()).rejects.toThrow('没有访问权限')
    expect(getToken()).toBe('test-token')
  })
  it('validates blank submissions without calling the server', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(sendChat(' \n ')).rejects.toThrow('请输入咨询事项')
    expect(fetch).not.toHaveBeenCalled()
  })
  it('reports network failures in actionable language', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(login('user@example.local', 'test')).rejects.toThrow('无法连接服务')
  })
  it('aborts a timed-out request and releases its timer', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })))
    const result = expect(fetchReadiness()).rejects.toThrow('请求超时')
    await vi.advanceTimersByTimeAsync(20000)
    await result
    expect(vi.getTimerCount()).toBe(0)
  })
  it('propagates caller cancellation without reporting a network failure', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })))
    const request = fetchReadiness(controller.signal)
    controller.abort()
    await expect(request).rejects.toHaveProperty('name', 'AbortError')
  })
})
