import { useState } from 'react'
import { useAuth } from '@/state/auth'

export function Login() {
  const login = useAuth((s) => s.login)
  const [token, setToken] = useState('')

  return (
    <div className="flex h-full items-center justify-center bg-neutral-50">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          login(token.trim())
        }}
        className="w-80 space-y-4 rounded-lg border border-neutral-200 bg-white p-6 shadow-sm"
      >
        <div>
          <h1 className="text-lg font-semibold text-neutral-900">IFCBox</h1>
          <p className="text-sm text-neutral-500">Enter the app token to continue.</p>
        </div>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="App token (blank for local dev)"
          className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm outline-none focus:border-neutral-900"
          autoFocus
        />
        <button
          type="submit"
          className="w-full rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700"
        >
          Continue
        </button>
      </form>
    </div>
  )
}
