import { create } from 'zustand'

export type OverlayKind = 'none' | 'occupancy' | 'clearance'

interface ViewerState {
  overlay: OverlayKind
  clip: boolean
  clipHeight: number
  setOverlay: (o: OverlayKind) => void
  setClip: (c: boolean) => void
  setClipHeight: (h: number) => void
}

export const useViewer = create<ViewerState>((set) => ({
  overlay: 'none',
  clip: false,
  clipHeight: 0,
  setOverlay: (o) => set({ overlay: o }),
  setClip: (c) => set({ clip: c }),
  setClipHeight: (h) => set({ clipHeight: h }),
}))
