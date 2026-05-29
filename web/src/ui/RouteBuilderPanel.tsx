import { useMemo, useState } from 'react'
import { useRouteBuilder } from '@/state/routeBuilder'
import type { AnchorSel } from '@/state/routeBuilder'
import type { FloorDetail } from '@/api/types'

function Seg<T extends string>(props: {
  value: T
  options: { v: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="flex overflow-hidden rounded-md border border-neutral-700 text-xs">
      {props.options.map((o) => (
        <button
          key={o.v}
          onClick={() => props.onChange(o.v)}
          className={`flex-1 px-2 py-1 ${
            props.value === o.v ? 'bg-neutral-100 text-neutral-900' : 'text-neutral-300'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function RouteBuilderPanel({ floor }: { floor: FloorDetail }) {
  const source = useRouteBuilder((s) => s.source)
  const targets = useRouteBuilder((s) => s.targets)
  const mode = useRouteBuilder((s) => s.mode)
  const pickMode = useRouteBuilder((s) => s.pickMode)
  const setPickMode = useRouteBuilder((s) => s.setPickMode)
  const setMode = useRouteBuilder((s) => s.setMode)
  const pick = useRouteBuilder((s) => s.pick)
  const removeTarget = useRouteBuilder((s) => s.removeTarget)
  const clearSource = useRouteBuilder((s) => s.clearSource)
  const reset = useRouteBuilder((s) => s.reset)

  const [q, setQ] = useState('')
  const items = useMemo<AnchorSel[]>(() => {
    const all: AnchorSel[] = [
      ...floor.terminals.map((t) => ({ kind: 'terminal' as const, id: t.id, label: t.id })),
      ...floor.spaces.map((s) => ({ kind: 'room' as const, id: s.id, label: s.name })),
    ]
    const needle = q.toLowerCase()
    return all.filter((i) => i.label.toLowerCase().includes(needle))
  }, [floor, q])

  return (
    <div className="absolute top-3 right-3 bottom-3 flex w-72 flex-col gap-3 overflow-hidden rounded-lg border border-neutral-700 bg-neutral-900/90 p-3 text-neutral-100 backdrop-blur">
      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-400">Picking assigns to</p>
        <Seg
          value={pickMode}
          onChange={setPickMode}
          options={[
            { v: 'source', label: 'Source' },
            { v: 'target', label: 'Target' },
          ]}
        />
        <p className="text-[11px] text-neutral-500">
          Click a marker or a wall in the 3D view, or a row below.
        </p>
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-400">Mode</p>
        <Seg
          value={mode}
          onChange={setMode}
          options={[
            { v: 'trunk', label: 'Trunk' },
            { v: 'independent', label: 'Independent' },
          ]}
        />
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-400">Source</p>
        {source ? (
          <div className="flex items-center justify-between rounded bg-green-600/20 px-2 py-1 text-xs">
            <span className="truncate">
              {source.kind}: {source.label}
            </span>
            <button onClick={clearSource} className="text-neutral-400 hover:text-white">
              ✕
            </button>
          </div>
        ) : (
          <p className="text-xs text-neutral-500">none — pick a source</p>
        )}
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-neutral-400">Targets ({targets.length})</p>
        <div className="max-h-28 space-y-1 overflow-auto">
          {targets.map((t, i) => (
            <div
              key={`${t.id ?? 'pt'}-${i}`}
              className="flex items-center justify-between rounded bg-blue-600/20 px-2 py-1 text-xs"
            >
              <span className="truncate">
                {t.kind}: {t.label}
              </span>
              <button onClick={() => removeTarget(i)} className="text-neutral-400 hover:text-white">
                ✕
              </button>
            </div>
          ))}
          {targets.length === 0 && <p className="text-xs text-neutral-500">none</p>}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-1">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search terminals / rooms"
          className="rounded border border-neutral-700 bg-neutral-800 px-2 py-1 text-xs outline-none"
        />
        <ul className="min-h-0 flex-1 divide-y divide-neutral-800 overflow-auto rounded border border-neutral-800">
          {items.map((it) => (
            <li key={`${it.kind}-${it.id}`}>
              <button
                onClick={() => pick(it)}
                className="flex w-full items-center gap-2 px-2 py-1 text-left text-xs hover:bg-neutral-800"
              >
                <span className={it.kind === 'terminal' ? 'text-amber-400' : 'text-cyan-400'}>
                  {it.kind === 'terminal' ? '◈' : '▢'}
                </span>
                <span className="truncate">{it.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <button
        onClick={reset}
        className="rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-800"
      >
        Reset selection
      </button>
    </div>
  )
}
