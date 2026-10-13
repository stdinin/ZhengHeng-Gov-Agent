import type {
  AgentNetworkResponse,
  ApiError,
  ChatResponse,
  LoginResponse,
  ReadinessPayload,
  TracePayload,
} from '../types/api'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

async function readJson(response: Response): Promise<unknown> {
  return response.json()
}

export async function fetchReadiness(): Promise<ReadinessPayload> {
  const response = await fetch(`${apiBaseUrl}/health/ready`)
  const payload = await readJson(response)
  if (response.ok) {
    return payload as ReadinessPayload
  }

  const errorPayload = payload as ApiError
  const dependencies = errorPayload.error.details.dependencies
  if (typeof dependencies === 'object' && dependencies !== null) {
    return { status: 'unready', dependencies: dependencies as ReadinessPayload['dependencies'] }
  }
  throw new Error(errorPayload.error.message)
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const response = await fetch(`${apiBaseUrl}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const payload = await readJson(response)
  if (!response.ok) {
    throw new Error((payload as ApiError).error.message)
  }
  return payload as LoginResponse
}

function accessToken(): string {
  const token = sessionStorage.getItem('zhengheng_access_token')
  if (!token) {
    throw new Error('请先登录后再使用政策问答。')
  }
  return token
}

export async function sendChat(query: string, sessionId?: string): Promise<ChatResponse> {
  const response = await fetch(`${apiBaseUrl}/chat`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken()}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query, session_id: sessionId }),
  })
  const payload = await readJson(response)
  if (!response.ok) {
    throw new Error((payload as ApiError).error.message)
  }
  return payload as ChatResponse
}

export async function fetchTrace(traceId: string): Promise<TracePayload> {
  const response = await fetch(`${apiBaseUrl}/traces/${encodeURIComponent(traceId)}`, {
    headers: { Authorization: `Bearer ${accessToken()}` },
  })
  const payload = await readJson(response)
  if (!response.ok) {
    throw new Error((payload as ApiError).error.message)
  }
  return payload as TracePayload
}

export async function fetchAgentNetwork(): Promise<AgentNetworkResponse> {
  const response = await fetch(`${apiBaseUrl}/admin/agent-network`, {
    headers: { Authorization: `Bearer ${accessToken()}` },
  })
  const payload = await readJson(response)
  if (!response.ok) {
    throw new Error((payload as ApiError).error.message)
  }
  return payload as AgentNetworkResponse
}
