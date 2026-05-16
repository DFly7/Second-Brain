import { useEffect, useRef } from 'react'
import { createSSE } from '../api/client'

export function useSse(onEvent: (data: unknown) => void): void {
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent
  useEffect(() => {
    return createSSE((data) => handlerRef.current(data))
  }, [])
}
