import { create } from 'zustand'

interface SelectionState {
  modelId: string | null
  floorIndex: number | null
  openModel: (id: string) => void
  closeModel: () => void
  openFloor: (n: number) => void
  closeFloor: () => void
}

export const useSelection = create<SelectionState>((set) => ({
  modelId: null,
  floorIndex: null,
  openModel: (id) => set({ modelId: id, floorIndex: null }),
  closeModel: () => set({ modelId: null, floorIndex: null }),
  openFloor: (n) => set({ floorIndex: n }),
  closeFloor: () => set({ floorIndex: null }),
}))
