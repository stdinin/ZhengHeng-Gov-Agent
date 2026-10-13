import type { AgentNetworkResponse, ChatResponse, LoginResponse, ReadinessPayload, TracePayload } from '../types/api'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1').replace(/\/$/, '')
const tokenKey = 'zhengheng_access_token'
export const sessionEvent = 'zhengheng-session-expired'

export class RequestError extends Error {
  constructor(message: string, public status = 0) { super(message); this.name = 'RequestError' }
}
export function getToken() {
  try { return sessionStorage.getItem(tokenKey) } catch { return null }
}
export function saveToken(token: string) {
  try { sessionStorage.setItem(tokenKey, token) } catch {
    throw new RequestError('浏览器无法保存登录状态，请允许此站点使用会话存储后重试。')
  }
}
export function clearToken() {
  try { sessionStorage.removeItem(tokenKey) } catch { /* Storage may be disabled. */ }
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(item => typeof item === 'string')
const number = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v >= 0
const userValid = (v: unknown): v is LoginResponse['user'] => record(v) && typeof v.id === 'string' && typeof v.email === 'string' && ['USER', 'DEPT_ADMIN', 'SUPER_ADMIN'].includes(String(v.role))
type Options = { signal?: AbortSignal; auth?: boolean; body?: unknown; timeout?: number; readiness?: boolean }
async function request<T>(path: string, valid: (value: unknown) => value is T, options: Options = {}): Promise<T> {
  const token = options.auth ? getToken() : null
  if (options.auth && !token) throw new RequestError('请先登录后再使用此功能。', 401)
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort()
  if (options.signal?.aborted) controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, options.timeout ?? 20000)
  try {
    const response = await fetch(apiBaseUrl + path, {
      method: options.body === undefined ? 'GET' : 'POST',
      headers: { ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    })
    if (response.status === 401 && options.auth) {
      if (getToken() === token) { clearToken(); window.dispatchEvent(new Event(sessionEvent)) }
      throw new RequestError('登录已失效，请重新登录。', 401)
    }
    let payload: unknown
    try { payload = await response.json() } catch {
      throw new RequestError(response.ok ? '服务返回的数据格式异常，请重试。' : '服务暂时不可用，请稍后重试。', response.status)
    }
    if (options.readiness && response.status === 503 && record(payload) && record(payload.error) && record(payload.error.details)) {
      const status = { status: 'unready', dependencies: payload.error.details.dependencies }
      if (valid(status)) return status
    }
    if (!response.ok) {
      const messages: Record<number, string> = {
        401: '邮箱或密码不正确，请检查后重试。', 403: '当前账户没有访问权限，请联系管理员。',
        404: '未找到该记录，请检查编号是否正确。', 422: '提交内容不符合要求，请检查后重试。',
        429: '请求过于频繁，请稍后重试。', 503: '服务暂时不可用，可在“系统状态”中查看详情。',
      }
      throw new RequestError(messages[response.status] ?? '请求未完成，请稍后重试。', response.status)
    }
    if (!valid(payload)) throw new RequestError('服务返回的数据不完整，请重试或联系管理员。')
    return payload
  } catch (error) {
    if (timedOut) throw new RequestError('请求超时，请稍后重试。')
    if (controller.signal.aborted) throw new DOMException('请求已取消', 'AbortError')
    if (error instanceof RequestError) throw error
    throw new RequestError('无法连接服务，请检查网络或稍后重试。')
  } finally {
    window.clearTimeout(timer)
    options.signal?.removeEventListener('abort', abort)
  }
}
function readinessValid(v: unknown): v is ReadinessPayload {
  return record(v) && typeof v.status === 'string' && record(v.dependencies) && Object.values(v.dependencies).every(d =>
    record(d) && typeof d.name === 'string' && typeof d.ready === 'boolean' && number(d.latency_ms) && (d.error == null || typeof d.error === 'string'))
}
export const fetchReadiness = (signal?: AbortSignal) => request('/health/ready', readinessValid, { signal, readiness: true })
export const fetchCurrentUser = (signal?: AbortSignal) => request('/auth/me', userValid, { signal, auth: true })
export const login = (email: string, password: string, signal?: AbortSignal) => request('/auth/login', (v): v is LoginResponse =>
  record(v) && typeof v.access_token === 'string' && v.access_token.length > 0 && userValid(v.user), { body: { email, password }, signal })
function chatValid(v: unknown): v is ChatResponse {
  if (!record(v) || !['SUCCESS', 'ABSTAIN'].includes(String(v.status)) || typeof v.answer !== 'string' || typeof v.trace_id !== 'string' || typeof v.session_id !== 'string' || !number(v.attempts) || !strings(v.warnings)) return false
  if (!Array.isArray(v.citations) || !v.citations.every(c => record(c) && ['id', 'chunk_id', 'title', 'department', 'status', 'excerpt'].every(k => typeof c[k] === 'string') && ['source_url', 'written_date', 'document_number'].every(k => c[k] == null || typeof c[k] === 'string'))) return false
  if (v.orchestration != null) {
    const o = v.orchestration
    if (!record(o) || !strings(o.requested_departments) || !strings(o.completed_departments) || typeof o.partial !== 'boolean' || !number(o.fanout) || !Array.isArray(o.failed_departments) || !o.failed_departments.every(d => record(d) && typeof d.dept_id === 'string' && typeof d.reason === 'string')) return false
  }
  return true
}
export function sendChat(query: string, sessionId?: string, signal?: AbortSignal) {
  if (!query.trim()) return Promise.reject(new RequestError('请输入咨询事项。'))
  return request('/chat', chatValid, { auth: true, signal, timeout: 120000, body: { query: query.trim(), session_id: sessionId } })
}
function traceValid(v: unknown): v is TracePayload {
  return record(v) && ['id', 'session_id', 'query', 'answer', 'created_at'].every(k => typeof v[k] === 'string') && ['SUCCESS', 'ABSTAIN'].includes(String(v.status)) && Array.isArray(v.nodes) && v.nodes.every(n => record(n) && typeof n.node === 'string' && number(n.latency_ms) && typeof n.fallback === 'boolean') && (v.child_trace_ids == null || strings(v.child_trace_ids)) && ['parent_trace_id', 'trace_kind', 'execution_mode', 'agent_id', 'dept_id'].every(k => v[k] == null || typeof v[k] === 'string')
}
export const fetchTrace = (id: string, signal?: AbortSignal) => request('/traces/' + encodeURIComponent(id.trim()), traceValid, { auth: true, signal })
function networkValid(v: unknown): v is AgentNetworkResponse {
  return record(v) && typeof v.orchestrator_health === 'string' && typeof v.pi_runtime_health === 'string' && Array.isArray(v.members) && v.members.every(m => record(m) && ['agent_id', 'dept_id', 'health', 'runtime_backend'].every(k => typeof m[k] === 'string') && number(m.timeout_count) && (m.recent_latency_ms === null || number(m.recent_latency_ms)) && (m.latest_child_trace_id === null || typeof m.latest_child_trace_id === 'string'))
}
export const fetchAgentNetwork = (signal?: AbortSignal) => request('/admin/agent-network', networkValid, { auth: true, signal })
