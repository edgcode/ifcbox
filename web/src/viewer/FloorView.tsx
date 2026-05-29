import { Suspense, useEffect, useMemo } from 'react'
import { Canvas } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Bounds, Loader, OrbitControls } from '@react-three/drei'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useSelection } from '@/state/selection'
import { useRouteBuilder } from '@/state/routeBuilder'
import { useRouteResults } from '@/state/routeResults'
import { useViewer } from '@/state/viewer'
import { RouteBuilderPanel } from '@/ui/RouteBuilderPanel'
import { ViewerControls } from '@/ui/ViewerControls'
import { Legend } from '@/ui/Legend'
import { BimShell } from './BimShell'
import { Clipping } from './Clipping'
import { Markers } from './Markers'
import { OverlayPlane } from './OverlayPlane'
import { PipeNetwork } from './PipeNetwork'
import { buildScale } from './colors'

export function FloorView({ modelId, floorIndex }: { modelId: string; floorIndex: number }) {
  const closeFloor = useSelection((s) => s.closeFloor)
  const pick = useRouteBuilder((s) => s.pick)
  const reset = useRouteBuilder((s) => s.reset)
  const groups = useRouteBuilder((s) => s.groups)
  const results = useRouteResults((s) => s.byGroup)
  const clearResults = useRouteResults((s) => s.clear)
  const overlay = useViewer((s) => s.overlay)
  const clip = useViewer((s) => s.clip)
  const clipHeight = useViewer((s) => s.clipHeight)
  const setClipHeight = useViewer((s) => s.setClipHeight)
  const colorMode = useViewer((s) => s.colorMode)

  const floor = useQuery({
    queryKey: ['floor', modelId, floorIndex],
    queryFn: () => api.floorDetail(modelId, floorIndex),
  })
  const walls = useQuery({
    queryKey: ['walls', modelId, floorIndex],
    queryFn: () => api.getWalls(modelId, floorIndex),
    enabled: floor.data?.status === 'ready',
  })
  const url = api.geometryUrl(modelId, floorIndex)
  const grid = floor.data?.grid
  const scale = useMemo(() => buildScale(colorMode, walls.data ?? {}), [colorMode, walls.data])

  // Clear the route builder + results when switching floors/models.
  useEffect(() => {
    reset()
    clearResults()
  }, [modelId, floorIndex, reset, clearResults])

  // Initialise the clip height just above the routing elevation once known.
  useEffect(() => {
    if (grid) setClipHeight(grid.pipe_z + 1)
  }, [grid, setClipHeight])

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
        {floor.isLoading && <span className="text-xs text-neutral-500">loading…</span>}
        {floor.error && <span className="text-xs text-red-400">failed to load floor</span>}
      </header>

      <div className="relative flex-1">
        <Canvas
          // Z-up scene to match IFC/Revit world coords (shell, markers, pipe all share it)
          camera={{ up: [0, 0, 1], position: [25, -30, 20], fov: 50, near: 0.1, far: 5000 }}
        >
          <ambientLight intensity={0.7} />
          <directionalLight position={[40, -30, 60]} intensity={1.3} />
          <directionalLight position={[-30, 20, 30]} intensity={0.5} />
          <Clipping enabled={clip} height={clipHeight} />

          {overlay !== 'none' && grid && (
            <Suspense fallback={null}>
              <OverlayPlane
                key={overlay}
                grid={grid}
                url={api.overlayUrl(modelId, floorIndex, overlay)}
                crisp={overlay === 'occupancy'}
              />
            </Suspense>
          )}
          <Suspense fallback={null}>
            {/* Fit once when the shell loads (no `observe`, which refits on every
                re-render and sends the camera flying when a marker is clicked). */}
            <Bounds fit clip margin={1.2}>
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
                <BimShell url={url} walls={walls.data} scale={scale} />
              </group>
            </Bounds>
            {floor.data && <Markers floor={floor.data} />}
          </Suspense>

          {groups.map((g) => {
            const r = results[g.id]
            return r ? (
              <Suspense key={g.id} fallback={null}>
                <PipeNetwork url={api.meshUrl(r.route_id)} color={g.color} />
              </Suspense>
            ) : null
          })}
          {groups.map((g) => {
            const r = results[g.id]
            if (!r) return null
            return r.branch_points.map((p, i) => (
              <mesh key={`${g.id}-${i}`} position={p as [number, number, number]}>
                {/* junction ~1.5x the pipe diameter */}
                <sphereGeometry args={[(r.diameter_m * 1.5) / 2, 16, 16]} />
                <meshStandardMaterial color={g.color} emissive={g.color} emissiveIntensity={0.5} />
              </mesh>
            ))
          })}

          <OrbitControls makeDefault enableDamping />
        </Canvas>
        <Loader />
        <ViewerControls grid={grid} />
        <Legend scale={scale} walls={walls.data} />
        {floor.data && (
          <RouteBuilderPanel modelId={modelId} floorIndex={floorIndex} floor={floor.data} />
        )}
      </div>
    </div>
  )
}
