export type DependencyStatus = {
  name: string
  ready: boolean
  latency_ms: number
  error?: string | null
}

export type ReadinessPayload = {
  status: string
  dependencies: Record<string, DependencyStatus>
}

export type ApiError = {
  error: {
    code: string
    message: string
    details: Record<string, unknown>
    trace_id: string
  }
}

export type LoginResponse = {
  access_token: string
  token_type: 'bearer'
  user: {
    id: string
    email: string
    role: 'USER' | 'DEPT_ADMIN' | 'SUPER_ADMIN'
  }
}

export type Citation = {
  id: string
  chunk_id: string
  title: string
  department: string
  status: string
  excerpt: string
  document_number?: string | null
  written_date?: string | null
  source_url?: string | null
}

export type ChatResponse = {
  trace_id: string
  session_id: string
  status: 'SUCCESS' | 'ABSTAIN'
  answer: string
  citations: Citation[]
  attempts: number
  warnings: string[]
}

export type TracePayload = {
  id: string
  session_id: string
  query: string
  status: 'SUCCESS' | 'ABSTAIN'
  answer: string
  created_at: string
  nodes: Array<{
    node: string
    latency_ms: number
    fallback: boolean
    applied_strategy_ids: string[]
  }>
}
