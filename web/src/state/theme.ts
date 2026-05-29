import { create } from 'zustand'

type Theme = 'light' | 'dark'
const KEY = 'ifcbox_theme'

function apply(t: Theme): void {
  document.documentElement.classList.toggle('dark', t === 'dark')
}

const initial: Theme = (localStorage.getItem(KEY) as Theme) || 'dark'
apply(initial) // run at import so the class is set before first paint

interface ThemeState {
  theme: Theme
  toggle: () => void
}

export const useTheme = create<ThemeState>((set) => ({
  theme: initial,
  toggle: () =>
    set((s) => {
      const t: Theme = s.theme === 'dark' ? 'light' : 'dark'
      localStorage.setItem(KEY, t)
      apply(t)
      return { theme: t }
    }),
}))
