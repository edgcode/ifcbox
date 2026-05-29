import { create } from 'zustand'

export type OverlayKind = 'none' | 'occupancy' | 'clearance'

interface ViewerState {
  overlay: OverlayKind
  clip: boolean
  clipHeight: number
  showTerminals: boolean
  showRooms: boolean
  showLabels: boolean
  setOverlay: (o: OverlayKind) => void
  setClip: (c: boolean) => void
  setClipHeight: (h: number) => void
  toggle: (k: 'showTerminals' | 'showRooms' | 'showLabels') => void
}

export const useViewer = create<ViewerState>((set) => ({
  overlay: 'none',
  clip: false,
  clipHeight: 0,
  showTerminals: true,
  showRooms: true,
  showLabels: true,
  setOverlay: (o) => set({ overlay: o }),
  setClip: (c) => set({ clip: c }),
  setClipHeight: (h) => set({ clipHeight: h }),
  toggle: (k) => set((st) => ({ [k]: !st[k] }) as Partial<ViewerState>),
}))
