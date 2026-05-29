import type { Walls, WallAttrs } from '@/api/types'

export type ColorMode = 'default' | 'thickness' | 'walltype' | 'firerating'

export const DEFAULT_COLOR = '#9ca3af'
export const NA_COLOR = '#6b7280'

const PALETTE = [
  '#ef4444', '#f59e0b', '#eab308', '#84cc16', '#22c55e', '#14b8a6',
  '#06b6d4', '#3b82f6', '#6366f1', '#8b5cf6', '#a855f7', '#d946ef',
  '#ec4899', '#f43f5e', '#10b981', '#0ea5e9', '#7c3aed', '#65a30d',
  '#0891b2', '#dc2626',
]

// Continuous ramp blue -> green -> red over t in [0,1].
const STOPS = [
  [0.0, [59, 130, 246]],
  [0.5, [34, 197, 94]],
  [1.0, [239, 68, 68]],
] as const

function hex([r, g, b]: number[]): string {
  return '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')
}

export function rampColor(t: number): string {
  const x = Math.max(0, Math.min(1, t))
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i]
    if (x <= t1) {
      const [t0, c0] = STOPS[i - 1]
      const f = (x - t0) / (t1 - t0 || 1)
      return hex(c0.map((c, k) => c + (c1[k] - c) * f))
    }
  }
  return hex(STOPS[STOPS.length - 1][1] as unknown as number[])
}

export function categoryColor(value: string, categories: string[]): string {
  const i = categories.indexOf(value)
  return PALETTE[(i < 0 ? 0 : i) % PALETTE.length]
}

// Cap the thickness colour scale so thin walls keep colour variation instead of
// being washed out by thick structural elements (e.g. 1.2 m stairs).
const THICKNESS_CAP_M = 0.5

export interface Scale {
  mode: ColorMode
  categories: string[]
  min: number
  max: number
  capped: boolean
}

export function buildScale(mode: ColorMode, walls: Walls): Scale {
  const vals = Object.values(walls)
  if (mode === 'thickness') {
    // Walls only — exclude stairs / ramps / columns (wall_type_name === '—').
    const ts = vals.filter((w) => w.wall_type_name !== '—').map((w) => w.thickness_m)
    const dataMax = ts.length ? Math.max(...ts) : 1
    const min = ts.length ? Math.min(...ts) : 0
    return { mode, categories: [], min, max: Math.min(dataMax, THICKNESS_CAP_M), capped: dataMax > THICKNESS_CAP_M }
  }
  if (mode === 'walltype' || mode === 'firerating') {
    const key = mode === 'walltype' ? 'wall_type_name' : 'fire_rating'
    const cats = [...new Set(vals.map((w) => w[key as keyof WallAttrs] as string))]
      .filter((v) => v !== '—')
      .sort()
    return { mode, categories: cats, min: 0, max: 1, capped: false }
  }
  return { mode, categories: [], min: 0, max: 1, capped: false }
}

export function colorFor(attr: WallAttrs | undefined, scale: Scale): string {
  if (!attr || scale.mode === 'default') return DEFAULT_COLOR
  if (scale.mode === 'thickness') {
    if (attr.wall_type_name === '—') return NA_COLOR // non-wall (stairs/ramps/columns)
    const span = scale.max - scale.min || 1
    return rampColor((attr.thickness_m - scale.min) / span)
  }
  const value = scale.mode === 'walltype' ? attr.wall_type_name : attr.fire_rating
  if (value === '—') return NA_COLOR
  return categoryColor(value, scale.categories)
}
