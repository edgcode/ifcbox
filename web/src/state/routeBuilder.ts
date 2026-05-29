import { create } from 'zustand'
import type { AnchorIn, RouteMode } from '@/api/types'

export type PickKind = 'point' | 'terminal' | 'room'
export type PickMode = 'source' | 'target'

export interface AnchorSel {
  kind: PickKind
  id?: string
  xyz?: [number, number, number]
  label: string
}

export function toAnchorIn(a: AnchorSel): AnchorIn {
  return { type: a.kind, id: a.id, xyz: a.xyz }
}

interface RouteBuilderState {
  source: AnchorSel | null
  targets: AnchorSel[]
  mode: RouteMode
  pickMode: PickMode
  setPickMode: (m: PickMode) => void
  setMode: (m: RouteMode) => void
  pick: (a: AnchorSel) => void
  removeTarget: (index: number) => void
  clearSource: () => void
  reset: () => void
}

export const useRouteBuilder = create<RouteBuilderState>((set) => ({
  source: null,
  targets: [],
  mode: 'trunk',
  pickMode: 'source',
  setPickMode: (m) => set({ pickMode: m }),
  setMode: (m) => set({ mode: m }),
  pick: (a) =>
    set((st) => {
      if (st.pickMode === 'source') return { source: a }
      if (a.id && st.targets.some((t) => t.id === a.id)) return {} // no duplicate marker
      return { targets: [...st.targets, a] }
    }),
  removeTarget: (index) => set((st) => ({ targets: st.targets.filter((_, i) => i !== index) })),
  clearSource: () => set({ source: null }),
  reset: () => set({ source: null, targets: [], pickMode: 'source' }),
}))
