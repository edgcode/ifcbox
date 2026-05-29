import { create } from 'zustand'
import type { AnchorSel } from './routeBuilder'

interface ContextMenuState {
  anchor: AnchorSel | null
  x: number
  y: number
  open: (anchor: AnchorSel, x: number, y: number) => void
  close: () => void
}

export const useContextMenu = create<ContextMenuState>((set) => ({
  anchor: null,
  x: 0,
  y: 0,
  open: (anchor, x, y) => set({ anchor, x, y }),
  close: () => set({ anchor: null }),
}))
