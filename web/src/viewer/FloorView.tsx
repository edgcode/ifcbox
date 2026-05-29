import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { Bounds, Loader, OrbitControls } from '@react-three/drei'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useSelection } from '@/state/selection'
import { BimShell } from './BimShell'

export function FloorView({ modelId, floorIndex }: { modelId: string; floorIndex: number }) {
  const closeFloor = useSelection((s) => s.closeFloor)
  const floor = useQuery({
    queryKey: ['floor', modelId, floorIndex],
    queryFn: () => api.floorDetail(modelId, floorIndex),
  })
  const url = api.geometryUrl(modelId, floorIndex)

  return (
    <div className="flex h-full flex-col bg-neutral-900 text-neutral-100">
      <header className="flex items-center gap-3 border-b border-neutral-800 px-6 py-3">
        <button onClick={closeFloor} className="text-sm text-neutral-400 hover:text-white">
          ← Storeys
        </button>
        <h1 className="text-base font-semibold">{floor.data?.name ?? `Floor ${floorIndex}`}</h1>
        {floor.data && (
          <span className="text-xs text-neutral-400">
            {floor.data.terminals.length} terminals · {floor.data.spaces.length} spaces
          </span>
        )}
      </header>

      <div className="relative flex-1">
        <Canvas
          // Z-up scene to match IFC/Revit world coords (shell, pipe, markers all share it)
          camera={{ up: [0, 0, 1], position: [25, -30, 20], fov: 50, near: 0.1, far: 5000 }}
        >
          <ambientLight intensity={0.7} />
          <directionalLight position={[40, -30, 60]} intensity={1.3} />
          <directionalLight position={[-30, 20, 30]} intensity={0.5} />
          <Suspense fallback={null}>
            <Bounds fit clip observe margin={1.2}>
              <BimShell url={url} />
            </Bounds>
          </Suspense>
          <OrbitControls makeDefault enableDamping />
        </Canvas>
        <Loader />
      </div>
    </div>
  )
}
