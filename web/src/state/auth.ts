import { create } from 'zustand'
import { getToken, setStoredToken } from '@/api/client'

const AUTHED_KEY = 'ifcbox_authed'

interface AuthState {
  token: string | null
  authed: boolean
  // `login` accepts an empty token for local dev (backend ignores auth when
  // IFCBOX_APP_TOKEN is unset); `authed` gates the UI either way.
  login: (token: string) => void
  logout: () => void
}

export const useAuth = create<AuthState>((set) => ({
  token: getToken(),
  authed: localStorage.getItem(AUTHED_KEY) === '1',
  login: (token: string) => {
    setStoredToken(token || null)
    localStorage.setItem(AUTHED_KEY, '1')
    set({ token: token || null, authed: true })
  },
  logout: () => {
    setStoredToken(null)
    localStorage.removeItem(AUTHED_KEY)
    set({ token: null, authed: false })
  },
}))
