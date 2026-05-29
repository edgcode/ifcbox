import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useViewer } from '@/state/viewer'
import type { OverlayKind } from '@/state/viewer'
import type { ColorMode } from '@/viewer/colors'
import type { GridMeta } from '@/api/types'

const OVERLAYS: { v: OverlayKind; label: string }[] = [
  { v: 'none', label: 'None' },
  { v: 'occupancy', label: 'Occupancy' },
  { v: 'clearance', label: 'SDF (clearance)' },
  { v: 'rooms', label: 'Room types' },
]

const COLOR_MODES: { v: ColorMode; label: string }[] = [
  { v: 'default', label: 'Default' },
  { v: 'thickness', label: 'Wall thickness' },
  { v: 'walltype', label: 'Wall type' },
  { v: 'firerating', label: 'Fire rating' },
]

export function ViewerControls({ grid }: { grid?: GridMeta | null }) {
  const overlay = useViewer((s) => s.overlay)
  const setOverlay = useViewer((s) => s.setOverlay)
  const clip = useViewer((s) => s.clip)
  const setClip = useViewer((s) => s.setClip)
  const clipHeight = useViewer((s) => s.clipHeight)
  const setClipHeight = useViewer((s) => s.setClipHeight)
  const showTerminals = useViewer((s) => s.showTerminals)
  const showRooms = useViewer((s) => s.showRooms)
  const showLabels = useViewer((s) => s.showLabels)
  const toggle = useViewer((s) => s.toggle)
  const colorMode = useViewer((s) => s.colorMode)
  const setColorMode = useViewer((s) => s.setColorMode)

  const roomClasses = useQuery({
    queryKey: ['room-classes'],
    queryFn: api.getRoomClasses,
    staleTime: Infinity,
    enabled: overlay === 'rooms',
  })

  const pz = grid?.pipe_z ?? 0
  const min = pz - 3
  const max = pz + 2

  return (
    <div className="absolute top-3 left-3 w-56 space-y-2 rounded-lg border border-neutral-300 bg-white/90 p-3 text-neutral-900 backdrop-blur dark:border-neutral-700 dark:bg-neutral-900/90 dark:text-neutral-100">
      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Wall colour</p>
        <select
          value={colorMode}
          onChange={(e) => setColorMode(e.target.value as ColorMode)}
          className="w-full rounded-md border border-neutral-300 bg-white px-2 py-1 text-xs dark:border-neutral-700 dark:bg-neutral-800"
        >
          {COLOR_MODES.map((m) => (
            <option key={m.v} value={m.v}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Overlay</p>
        <select
          value={overlay}
          onChange={(e) => setOverlay(e.target.value as OverlayKind)}
          className="w-full rounded-md border border-neutral-300 bg-white px-2 py-1 text-xs dark:border-neutral-700 dark:bg-neutral-800"
        >
          {OVERLAYS.map((o) => (
            <option key={o.v} value={o.v}>
              {o.label}
            </option>
          ))}
        </select>
        {overlay === 'rooms' && roomClasses.data && (
          <ul className="mt-1 max-h-32 space-y-1 overflow-y-auto">
            {roomClasses.data.map((rc) => (
              <li key={rc.key} className="flex items-center gap-2 text-[11px]">
                <span className="h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: rc.color }} />
                <span className="truncate text-neutral-600 dark:text-neutral-300">{rc.label}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-1">
        <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-300">
          <input type="checkbox" checked={clip} onChange={(e) => setClip(e.target.checked)} />
          Clip top
        </label>
        {clip && (
          <input
            type="range"
            min={min}
            max={max}
            step={0.1}
            value={clipHeight}
            onChange={(e) => setClipHeight(Number(e.target.value))}
            className="w-full accent-blue-600"
          />
        )}
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Show</p>
        <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-300">
          <input type="checkbox" checked={showTerminals} onChange={() => toggle('showTerminals')} />
          Terminals
        </label>
        <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-300">
          <input type="checkbox" checked={showRooms} onChange={() => toggle('showRooms')} />
          Rooms
        </label>
        <label className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-300">
          <input type="checkbox" checked={showLabels} onChange={() => toggle('showLabels')} />
          Room labels
        </label>
      </div>
    </div>
  )
}
