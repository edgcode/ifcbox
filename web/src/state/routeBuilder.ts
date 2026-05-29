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

// A routing "system": one source feeding N targets, rendered in its own colour.
export interface RouteGroup {
  id: string
  color: string
  source: AnchorSel | null
  targets: AnchorSel[]
  mode: RouteMode
}

export const GROUP_COLORS = [
  '#2563eb', '#16a34a', '#db2777', '#d97706',
  '#7c3aed', '#0891b2', '#dc2626', '#4f46e5',
]

let seq = 0
function newGroup(): RouteGroup {
  const color = GROUP_COLORS[seq % GROUP_COLORS.length]
  seq += 1
  return { id: `g${seq}_${Date.now()}`, color, source: null, targets: [], mode: 'trunk' }
}

interface RouteBuilderState {
  groups: RouteGroup[]
  activeId: string
  pickMode: PickMode
  setPickMode: (m: PickMode) => void
  addGroup: () => void
  removeGroup: (id: string) => void
  setActive: (id: string) => void
  setMode: (id: string, m: RouteMode) => void
  pick: (a: AnchorSel) => void
  removeTarget: (id: string, index: number) => void
  clearSource: (id: string) => void
  reset: () => void
}

function mapGroup(groups: RouteGroup[], id: string, fn: (g: RouteGroup) => RouteGroup) {
  return groups.map((g) => (g.id === id ? fn(g) : g))
}

export const useRouteBuilder = create<RouteBuilderState>((set) => {
  const first = newGroup()
  return {
    groups: [first],
    activeId: first.id,
    pickMode: 'source',
    setPickMode: (m) => set({ pickMode: m }),

    addGroup: () =>
      set((st) => {
        const g = newGroup()
        return { groups: [...st.groups, g], activeId: g.id }
      }),

    removeGroup: (id) =>
      set((st) => {
        const groups = st.groups.filter((g) => g.id !== id)
        if (groups.length === 0) {
          const g = newGroup()
          return { groups: [g], activeId: g.id }
        }
        const activeId = st.activeId === id ? groups[0].id : st.activeId
        return { groups, activeId }
      }),

    setActive: (id) => set({ activeId: id }),
    setMode: (id, m) => set((st) => ({ groups: mapGroup(st.groups, id, (g) => ({ ...g, mode: m })) })),

    pick: (a) =>
      set((st) => ({
        groups: mapGroup(st.groups, st.activeId, (g) => {
          if (st.pickMode === 'source') return { ...g, source: a }
          if (a.id && g.targets.some((t) => t.id === a.id)) return g
          return { ...g, targets: [...g.targets, a] }
        }),
      })),

    removeTarget: (id, index) =>
      set((st) => ({
        groups: mapGroup(st.groups, id, (g) => ({
          ...g,
          targets: g.targets.filter((_, i) => i !== index),
        })),
      })),

    clearSource: (id) =>
      set((st) => ({ groups: mapGroup(st.groups, id, (g) => ({ ...g, source: null })) })),

    reset: () =>
      set(() => {
        const g = newGroup()
        return { groups: [g], activeId: g.id, pickMode: 'source' }
      }),
  }
})
