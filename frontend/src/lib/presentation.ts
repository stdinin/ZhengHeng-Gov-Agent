export function department(value: string) {
  return ({ tax: '税务部门', dept_tax: '税务部门', hrss: '人社部门', housing: '住建部门' } as Record<string, string>)[value] ?? value
}
export function safeSourceUrl(value?: string | null) {
  if (!value) return null
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null } catch { return null }
}
export function dateTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}
export const roleName = (value: string) => ({ USER: '普通用户', DEPT_ADMIN: '部门管理员', SUPER_ADMIN: '系统管理员' } as Record<string, string>)[value] ?? '用户'
export function navigate(page: string, id?: string) {
  window.location.hash = '/' + page + (id ? '?id=' + encodeURIComponent(id) : '')
}
