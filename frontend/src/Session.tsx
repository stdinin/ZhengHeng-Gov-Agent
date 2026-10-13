import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { clearToken, fetchCurrentUser, getToken, saveToken, sessionEvent } from './api/client'
import type { LoginResponse } from './types/api'

type Session = { user: LoginResponse['user'] | null; checking: boolean; notice: string | null; signIn: (result: LoginResponse) => void; signOut: () => void }
const SessionContext = createContext<Session | null>(null)
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Session['user']>(null)
  const [checking, setChecking] = useState(!!getToken())
  const [notice, setNotice] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    const expired = () => { setUser(null); setNotice('登录已失效，请重新登录。'); setChecking(false) }
    window.addEventListener(sessionEvent, expired)
    if (getToken()) {
      void fetchCurrentUser(controller.signal).then(value => {
        if (!controller.signal.aborted) setUser(value)
      }).catch(error => {
        if (!controller.signal.aborted) setNotice(error instanceof Error ? error.message : '暂时无法确认登录状态，请重新登录。')
      }).finally(() => { if (!controller.signal.aborted) setChecking(false) })
    }
    return () => { controller.abort(); window.removeEventListener(sessionEvent, expired) }
  }, [])
  function signIn(result: LoginResponse) { saveToken(result.access_token); setUser(result.user); setNotice(null); setChecking(false) }
  function signOut() { clearToken(); setUser(null); setNotice(null); setChecking(false) }
  return <SessionContext.Provider value={{ user, checking, notice, signIn, signOut }}>{children}</SessionContext.Provider>
}
export function useSession() {
  const session = useContext(SessionContext)
  if (!session) throw new Error('Missing SessionProvider')
  return session
}
