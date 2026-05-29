import { useAuth } from '@/state/auth'
import { useSelection } from '@/state/selection'
import { Login } from '@/ui/Login'
import { ModelsView } from '@/ui/ModelsView'
import { ModelView } from '@/ui/ModelView'
import { FloorView } from '@/viewer/FloorView'
import { Providers } from './providers'

function Shell() {
  const authed = useAuth((s) => s.authed)
  const modelId = useSelection((s) => s.modelId)
  const floorIndex = useSelection((s) => s.floorIndex)

  if (!authed) return <Login />
  if (!modelId) return <ModelsView />
  if (floorIndex !== null) return <FloorView modelId={modelId} floorIndex={floorIndex} />
  return <ModelView modelId={modelId} />
}

export default function App() {
  return (
    <Providers>
      <Shell />
    </Providers>
  )
}
