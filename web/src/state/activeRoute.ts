import { create } from 'zustand'
import type { RouteResult } from '@/api/types'

interface ActiveRouteState {
  result: RouteResult | null
  setResult: (r: RouteResult | null) => void
  clear: () => void
}

export const useActiveRoute = create<ActiveRouteState>((set) => ({
  result: null,
  setResult: (r) => set({ result: r }),
  clear: () => set({ result: null }),
}))
