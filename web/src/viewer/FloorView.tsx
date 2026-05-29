import { Suspense, useEffect, useMemo } from 'react'
import { Canvas } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Bounds, Loader, OrbitControls, useProgress } from '@react-three/drei'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useSelection } from '@/state/selection'
import { useRouteBuilder } from '@/state/routeBuilder'
import { useRouteResults } from '@/state/routeResults'
import { useViewer } from '@/state/viewer'
import { RouteBuilderPanel } from '@/ui/RouteBuilderPanel'
import { ViewerControls } from '@/ui/ViewerControls'
import { Legend } from '@/ui/Legend'
import { ContextMenu } from '@/ui/ContextMenu'
import { ThemeToggle } from '@/ui/ThemeToggle'
import { BimShell } from './BimShell'
import { Clipping } from './Clipping'
import { Markers } from './Markers'
import { OverlayPlane } from './OverlayPlane'
import { PipeNetwork } from './PipeNetwork'
import { PointMarkers } from './PointMarkers'
import { buildScale } from './colors'

function ViewerLoading({ floorName, floorLoading }: { floorName?: string; floorLoading: boolean }) {
  const { progress, active } = useProgress()
  const show = floorLoading || active
  if (!show) return null
  const label = floorLoading
    ? 'Fetching floor data…'
    : `Loading 3D model — ${Math.round(progress)}%`
  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-white/50 backdrop-blur-sm dark:bg-neutral-900/50">
      <div className="flex items-center gap-3 rounded-lg border border-neutral-200 bg-white px-5 py-4 shadow-xl dark:border-neutral-700 dark:bg-neutral-800">
        <svg className="h-7 w-7 shrink-0 animate-spin text-blue-600 dark:text-blue-400"
             viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
          <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <div className="min-w-0">
          <p className="text-sm font-medium">{floorName ?? 'Floor'}</p>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">{label}</p>
        </div>
      </div>
    </div>
  )
}

export function FloorView({ modelId, floorIndex }: { modelId: string; floorIndex: number }) {
  const closeFloor = useSelection((s) => s.closeFloor)
  const pick = useRouteBuilder((s) => s.pick)
  const editing = useRouteBuilder((s) => s.editing)
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
    <div className="flex h-full flex-col bg-neutral-100 text-neutral-900 dark:bg-neutral-900 dark:text-neutral-100">
      <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-3 dark:border-neutral-800">
        <div className="flex items-center gap-3">
          <button
            onClick={closeFloor}
            className="text-sm text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white"
          >
            ← Storeys
          </button>
          <h1 className="text-base font-semibold">{floor.data?.name ?? `Floor ${floorIndex}`}</h1>
          {floor.data && (
            <span className="text-xs text-neutral-500 dark:text-neutral-400">
              {floor.data.terminals.length} terminals · {floor.data.spaces.length} spaces
            </span>
          )}
          {floor.isLoading && <span className="text-xs text-neutral-500 dark:text-neutral-400">loading…</span>}
          {floor.error && <span className="text-xs text-red-500 dark:text-red-400">failed to load floor</span>}
        </div>
        <ThemeToggle />
      </header>

      <div className="relative flex-1">
        <Canvas
          // Z-up scene to match IFC/Revit world coords (shell, markers, pipe all share it)
          camera={{ up: [0, 0, 1], position: [25, -30, 20], fov: 50, near: 0.1, far: 5000 }}
        >
          <ambientLight intensity={0.7} />
          <directionalLight position={[40, -30, 60]} intensity={1.3} />
          <directionalLight position={[-30, 20, 30]} intensity={0.5} />
          {/* Only clip once clipHeight is initialised from the floor grid;
              otherwise default clip=true would hide everything above z=0. */}
          <Clipping enabled={clip && clipHeight > 0} height={clipHeight} />

          {overlay !== 'none' && grid && (
            <Suspense fallback={null}>
              <OverlayPlane
                key={overlay}
                grid={grid}
                url={api.overlayUrl(modelId, floorIndex, overlay)}
                crisp={overlay === 'occupancy' || overlay === 'rooms'}
              />
            </Suspense>
          )}
          <Suspense fallback={null}>
            {/* Fit once when the shell loads (no `observe`, which refits on every
                re-render and sends the camera flying when a marker is clicked). */}
            <Bounds fit clip margin={1.2}>
              <group
                onClick={(e: ThreeEvent<MouseEvent>) => {
                  if (!editing) return
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
            <PointMarkers />
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
        <ViewerLoading floorName={floor.data?.name} floorLoading={floor.isLoading} />
        <ViewerControls grid={grid} />
        <Legend scale={scale} walls={walls.data} />
        {floor.data && (
          <RouteBuilderPanel modelId={modelId} floorIndex={floorIndex} floor={floor.data} />
        )}
        <ContextMenu />
      </div>
    </div>
  )
}
