import { useCallback, useEffect, useRef, useState } from 'react'

/** Only the newest request may update a mounted view. */
export function useTask<T>() {
  const active = useRef<AbortController | null>(null)
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => () => { active.current?.abort() }, [])
  const cancel = useCallback(() => {
    active.current?.abort(); active.current = null; setLoading(false)
  }, [])
  const reset = useCallback(() => { cancel(); setData(null); setError(null) }, [cancel])
  const run = useCallback(async (job: (signal: AbortSignal) => Promise<T>, onSuccess?: (result: T) => void) => {
    active.current?.abort()
    const current = new AbortController()
    active.current = current
    setLoading(true); setError(null); setData(null)
    try {
      const result = await job(current.signal)
      if (!current.signal.aborted && active.current === current) { onSuccess?.(result); setData(result) }
    } catch (reason) {
      if (!current.signal.aborted && active.current === current) setError(reason instanceof Error ? reason.message : '操作未完成，请重试。')
    } finally {
      if (!current.signal.aborted && active.current === current) setLoading(false)
    }
  }, [])
  return { data, error, loading, run, cancel, reset }
}
