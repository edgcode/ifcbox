import { create } from 'zustand'
import type { ColorMode } from '@/viewer/colors'

export type OverlayKind = 'none' | 'occupancy' | 'clearance' | 'rooms'

interface ViewerState {
  overlay: OverlayKind
  clip: boolean
  clipHeight: number
  colorMode: ColorMode
  showTerminals: boolean
  showRooms: boolean
  showLabels: boolean
  setOverlay: (o: OverlayKind) => void
  setClip: (c: boolean) => void
  setClipHeight: (h: number) => void
  setColorMode: (m: ColorMode) => void
  toggle: (k: 'showTerminals' | 'showRooms' | 'showLabels') => void
}

export const useViewer = create<ViewerState>((set) => ({
  overlay: 'none',
  clip: false,
  clipHeight: 0,
  colorMode: 'default',
  showTerminals: true,
  showRooms: true,
  showLabels: true,
  setOverlay: (o) => set({ overlay: o }),
  setClip: (c) => set({ clip: c }),
  setClipHeight: (h) => set({ clipHeight: h }),
  setColorMode: (m) => set({ colorMode: m }),
  toggle: (k) => set((st) => ({ [k]: !st[k] }) as Partial<ViewerState>),
}))
