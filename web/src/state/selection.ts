import { create } from 'zustand'

interface SelectionState {
  modelId: string | null
  openModel: (id: string) => void
  closeModel: () => void
}

export const useSelection = create<SelectionState>((set) => ({
  modelId: null,
  openModel: (id) => set({ modelId: id }),
  closeModel: () => set({ modelId: null }),
}))
