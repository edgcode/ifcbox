import type { Walls } from '@/api/types'
import { NA_COLOR, categoryColor, rampColor, type Scale } from '@/viewer/colors'

const TITLE: Record<Scale['mode'], string> = {
  default: '',
  thickness: 'Wall thickness',
  walltype: 'Wall type',
  firerating: 'Fire rating',
}

export function Legend({ scale, walls }: { scale: Scale; walls?: Walls }) {
  if (scale.mode === 'default' || !walls) return null

  return (
    <div className="absolute bottom-3 left-3 max-h-[40%] w-56 overflow-y-auto rounded-lg border border-neutral-300 bg-white/90 p-3 text-neutral-900 backdrop-blur dark:border-neutral-700 dark:bg-neutral-900/90 dark:text-neutral-100">
      <p className="mb-1 text-xs font-medium text-neutral-600 dark:text-neutral-300">{TITLE[scale.mode]}</p>

      {scale.mode === 'thickness' ? (
        <div className="space-y-1">
          <div
            className="h-3 w-full rounded"
            style={{ background: `linear-gradient(to right, ${rampColor(0)}, ${rampColor(0.5)}, ${rampColor(1)})` }}
          />
          <div className="flex justify-between text-[11px] text-neutral-500 dark:text-neutral-400">
            <span>{(scale.min * 1000).toFixed(0)} mm</span>
            <span>
              {(scale.max * 1000).toFixed(0)}
              {scale.capped ? '+' : ''} mm
            </span>
          </div>
        </div>
      ) : (
        <ul className="space-y-1">
          {scale.categories.map((c) => (
            <li key={c} className="flex items-center gap-2 text-[11px]">
              <span
                className="h-3 w-3 shrink-0 rounded-sm"
                style={{ backgroundColor: categoryColor(c, scale.categories) }}
              />
              <span className="truncate" title={c}>{c}</span>
            </li>
          ))}
          <li className="flex items-center gap-2 text-[11px]">
            <span className="h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: NA_COLOR }} />
            <span className="text-neutral-500 dark:text-neutral-400">— / other</span>
          </li>
        </ul>
      )}
    </div>
  )
}
