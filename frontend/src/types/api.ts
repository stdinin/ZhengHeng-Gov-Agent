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
  orchestration?: {
    mode: 'single' | 'multi' | 'abstain'
    requested_departments: string[]
    completed_departments: string[]
    failed_departments: Array<{ dept_id: string; reason: string }>
    partial: boolean
    fanout: number
  }
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
  parent_trace_id?: string | null
  trace_kind?: 'root' | 'child' | string
  execution_mode?: 'single_agent' | 'multi_agent' | 'department_agent' | string
  agent_id?: string | null
  dept_id?: string | null
  child_trace_ids?: string[]
  selected_departments?: string[]
  partial?: boolean
  failed_departments?: Array<{ dept_id: string; reason: string }>
}

export type AgentNetworkResponse = {
  orchestrator_health: string
  pi_runtime_health: string
  members: Array<{
    agent_id: string
    dept_id: string
    health: string
    runtime_backend: string
    recent_latency_ms: number | null
    timeout_count: number
    latest_child_trace_id: string | null
  }>
}
