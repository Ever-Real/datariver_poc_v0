import { useCallback, useEffect, useMemo, useRef } from 'react'

interface AbortSignalChannel {
  next: () => AbortSignal
  abort: () => void
}

export function useAbortSignalChannel(): AbortSignalChannel {
  const current = useRef<AbortController | undefined>(undefined)
  const abort = useCallback(() => {
    current.current?.abort()
    current.current = undefined
  }, [])
  const next = useCallback(() => {
    current.current?.abort()
    const controller = new AbortController()
    current.current = controller
    return controller.signal
  }, [])
  useEffect(() => abort, [abort])
  return useMemo(() => ({ next, abort }), [abort, next])
}
