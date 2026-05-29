import { useViewer } from '@/state/viewer'
import type { OverlayKind } from '@/state/viewer'
import type { GridMeta } from '@/api/types'

const OVERLAYS: { v: OverlayKind; label: string }[] = [
  { v: 'none', label: 'None' },
  { v: 'occupancy', label: 'Occupancy' },
  { v: 'clearance', label: 'SDF' },
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

  const pz = grid?.pipe_z ?? 0
  const min = pz - 3
  const max = pz + 2

  return (
    <div className="absolute top-3 left-3 w-56 space-y-2 rounded-lg border border-neutral-700 bg-neutral-900/90 p-3 text-neutral-100 backdrop-blur">
      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-400">Overlay</p>
        <div className="flex overflow-hidden rounded-md border border-neutral-700 text-xs">
          {OVERLAYS.map((o) => (
            <button
              key={o.v}
              onClick={() => setOverlay(o.v)}
              className={`flex-1 px-2 py-1 ${
                overlay === o.v ? 'bg-neutral-100 text-neutral-900' : 'text-neutral-300'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1">
        <label className="flex items-center gap-2 text-xs text-neutral-300">
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
            className="w-full"
          />
        )}
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-400">Show</p>
        <label className="flex items-center gap-2 text-xs text-neutral-300">
          <input type="checkbox" checked={showTerminals} onChange={() => toggle('showTerminals')} />
          Terminals
        </label>
        <label className="flex items-center gap-2 text-xs text-neutral-300">
          <input type="checkbox" checked={showRooms} onChange={() => toggle('showRooms')} />
          Rooms
        </label>
        <label className="flex items-center gap-2 text-xs text-neutral-300">
          <input type="checkbox" checked={showLabels} onChange={() => toggle('showLabels')} />
          Room labels
        </label>
      </div>
    </div>
  )
}
