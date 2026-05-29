import { Suspense, useEffect } from 'react'
import { Canvas } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Bounds, Loader, OrbitControls } from '@react-three/drei'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useSelection } from '@/state/selection'
import { useRouteBuilder } from '@/state/routeBuilder'
import { useActiveRoute } from '@/state/activeRoute'
import { RouteBuilderPanel } from '@/ui/RouteBuilderPanel'
import { BimShell } from './BimShell'
import { Markers } from './Markers'
import { PipeNetwork } from './PipeNetwork'

export function FloorView({ modelId, floorIndex }: { modelId: string; floorIndex: number }) {
  const closeFloor = useSelection((s) => s.closeFloor)
  const pick = useRouteBuilder((s) => s.pick)
  const reset = useRouteBuilder((s) => s.reset)
  const route = useActiveRoute((s) => s.result)
  const clearRoute = useActiveRoute((s) => s.clear)

  const floor = useQuery({
    queryKey: ['floor', modelId, floorIndex],
    queryFn: () => api.floorDetail(modelId, floorIndex),
  })
  const url = api.geometryUrl(modelId, floorIndex)

  // Clear the route builder + active route when switching floors/models.
  useEffect(() => {
    reset()
    clearRoute()
  }, [modelId, floorIndex, reset, clearRoute])

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
          // Z-up scene to match IFC/Revit world coords (shell, markers, pipe all share it)
          camera={{ up: [0, 0, 1], position: [25, -30, 20], fov: 50, near: 0.1, far: 5000 }}
        >
          <ambientLight intensity={0.7} />
          <directionalLight position={[40, -30, 60]} intensity={1.3} />
          <directionalLight position={[-30, 20, 30]} intensity={0.5} />
          <Suspense fallback={null}>
            <Bounds fit clip observe margin={1.2}>
              <group
                onClick={(e: ThreeEvent<MouseEvent>) => {
                  e.stopPropagation()
                  const p = e.point
                  pick({
                    kind: 'point',
                    xyz: [p.x, p.y, p.z],
                    label: `${p.x.toFixed(1)}, ${p.y.toFixed(1)}`,
                  })
                }}
              >
                <BimShell url={url} />
              </group>
              {floor.data && <Markers floor={floor.data} />}
            </Bounds>
          </Suspense>

          <Suspense fallback={null}>
            {route && <PipeNetwork url={api.meshUrl(route.route_id)} />}
          </Suspense>
          {route?.branch_points.map((p, i) => (
            <mesh key={i} position={p as [number, number, number]}>
              {/* junction ~1.5x the pipe diameter */}
              <sphereGeometry args={[(route.diameter_m * 1.5) / 2, 16, 16]} />
              <meshStandardMaterial color="#facc15" emissive="#facc15" emissiveIntensity={0.5} />
            </mesh>
          ))}

          <OrbitControls makeDefault enableDamping />
        </Canvas>
        <Loader />
        {floor.data && (
          <RouteBuilderPanel modelId={modelId} floorIndex={floorIndex} floor={floor.data} />
        )}
      </div>
    </div>
  )
}
