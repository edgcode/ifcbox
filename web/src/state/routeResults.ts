import { create } from 'zustand'
import type { RouteResult } from '@/api/types'

// Route results keyed by routing-group id (one rendered pipe per group).
interface RouteResultsState {
  byGroup: Record<string, RouteResult>
  setResult: (groupId: string, r: RouteResult) => void
  removeResult: (groupId: string) => void
  clear: () => void
}

export const useRouteResults = create<RouteResultsState>((set) => ({
  byGroup: {},
  setResult: (groupId, r) => set((st) => ({ byGroup: { ...st.byGroup, [groupId]: r } })),
  removeResult: (groupId) =>
    set((st) => {
      const next = { ...st.byGroup }
      delete next[groupId]
      return { byGroup: next }
    }),
  clear: () => set({ byGroup: {} }),
}))
