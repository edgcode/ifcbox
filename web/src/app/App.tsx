import { useAuth } from '@/state/auth'
import { useSelection } from '@/state/selection'
import { Login } from '@/ui/Login'
import { ModelsView } from '@/ui/ModelsView'
import { ModelView } from '@/ui/ModelView'
import { Providers } from './providers'

function Shell() {
  const authed = useAuth((s) => s.authed)
  const modelId = useSelection((s) => s.modelId)

  if (!authed) return <Login />
  if (modelId) return <ModelView modelId={modelId} />
  return <ModelsView />
}

export default function App() {
  return (
    <Providers>
      <Shell />
    </Providers>
  )
}
