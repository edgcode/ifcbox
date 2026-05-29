import { useAuth } from '@/state/auth'
import { Login } from '@/ui/Login'
import { ModelsView } from '@/ui/ModelsView'
import { Providers } from './providers'

export default function App() {
  const authed = useAuth((s) => s.authed)
  return <Providers>{authed ? <ModelsView /> : <Login />}</Providers>
}
