import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { prepWsUrl } from '@/api/client'
import type { PrepProgress } from '@/api/types'

// Streams floor-prep progress over a WebSocket while `enabled`. On ready/error
// it invalidates the floor query so the UI reflects the final status.
export function usePrepProgress(
  modelId: string,
  floorIndex: number,
  enabled: boolean,
): PrepProgress | null {
  const [progress, setProgress] = useState<PrepProgress | null>(null)
  const qc = useQueryClient()

  useEffect(() => {
    if (!enabled) {
      setProgress(null)
      return
    }
    const ws = new WebSocket(prepWsUrl(modelId, floorIndex))
    ws.onmessage = (e) => {
      const p = JSON.parse(e.data) as PrepProgress
      setProgress(p)
      if (p.status === 'ready' || p.status === 'error') {
        qc.invalidateQueries({ queryKey: ['floor', modelId, floorIndex] })
        ws.close()
      }
    }
    return () => ws.close()
  }, [enabled, modelId, floorIndex, qc])

  return progress
}
