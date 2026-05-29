import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '@/api/client'
import { useRouteBuilder, toAnchorIn } from '@/state/routeBuilder'
import type { AnchorSel } from '@/state/routeBuilder'
import { useRouteResults } from '@/state/routeResults'
import type { FloorDetail, RouteResult } from '@/api/types'

function Seg<T extends string>(props: {
  value: T
  options: { v: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="flex overflow-hidden rounded-md border border-neutral-300 text-xs dark:border-neutral-700">
      {props.options.map((o) => (
        <button
          key={o.v}
          onClick={() => props.onChange(o.v)}
          className={`flex-1 px-2 py-1 ${
            props.value === o.v
              ? 'bg-blue-600 text-white'
              : 'text-neutral-600 dark:text-neutral-300'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function RouteBuilderPanel({
  modelId,
  floorIndex,
  floor,
}: {
  modelId: string
  floorIndex: number
  floor: FloorDetail
}) {
  const groups = useRouteBuilder((s) => s.groups)
  const activeId = useRouteBuilder((s) => s.activeId)
  const pickMode = useRouteBuilder((s) => s.pickMode)
  const setPickMode = useRouteBuilder((s) => s.setPickMode)
  const editing = useRouteBuilder((s) => s.editing)
  const setEditing = useRouteBuilder((s) => s.setEditing)
  const addGroup = useRouteBuilder((s) => s.addGroup)
  const removeGroup = useRouteBuilder((s) => s.removeGroup)
  const setActive = useRouteBuilder((s) => s.setActive)
  const setMode = useRouteBuilder((s) => s.setMode)
  const pick = useRouteBuilder((s) => s.pick)
  const removeTarget = useRouteBuilder((s) => s.removeTarget)
  const clearSource = useRouteBuilder((s) => s.clearSource)
  const loadApartments = useRouteBuilder((s) => s.loadApartments)
  const reset = useRouteBuilder((s) => s.reset)

  const byGroup = useRouteResults((s) => s.byGroup)
  const setResult = useRouteResults((s) => s.setResult)
  const clearResults = useRouteResults((s) => s.clear)
  const qc = useQueryClient()

  const active = groups.find((g) => g.id === activeId) ?? groups[0]

  const submitAll = useMutation({
    mutationFn: async () => {
      // Read groups via getState() so a just-dispatched loadApartments() is seen
      // before React re-renders this component.
      const current = useRouteBuilder.getState().groups
      const out: { gid: string; res: RouteResult }[] = []
      for (const g of current) {
        if (!g.source || g.targets.length === 0) continue
        const res = await api.submitRoute(modelId, floorIndex, {
          source: toAnchorIn(g.source),
          targets: g.targets.map(toAnchorIn),
          mode: g.mode,
        })
        out.push({ gid: g.id, res })
      }
      return out
    },
    onSuccess: (out) => {
      out.forEach(({ gid, res }) => setResult(gid, res))
      qc.invalidateQueries({ queryKey: ['routes', modelId] })
    },
  })

  const apartmentsQ = useQuery({
    queryKey: ['apartments', modelId, floorIndex],
    queryFn: () => api.getApartments(modelId, floorIndex),
    enabled: floor.status === 'ready',
    staleTime: Infinity,
  })

  const completeCount = groups.filter((g) => g.source && g.targets.length > 0).length
  const [q, setQ] = useState('')
  const items = useMemo<AnchorSel[]>(() => {
    const all: AnchorSel[] = [
      ...floor.terminals.map((t) => ({ kind: 'terminal' as const, id: t.id, label: t.id })),
      ...floor.spaces.map((s) => ({ kind: 'room' as const, id: s.id, label: s.name })),
    ]
    const needle = q.toLowerCase()
    return all.filter((i) => i.label.toLowerCase().includes(needle))
  }, [floor, q])

  const activeResult = byGroup[active.id]
  const label = 'text-xs font-medium text-neutral-500 dark:text-neutral-400'
  const chipX = 'text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white'

  return (
    <div className="absolute top-3 right-3 bottom-3 flex w-72 flex-col gap-3 overflow-y-auto rounded-lg border border-neutral-300 bg-white/90 p-3 text-neutral-900 backdrop-blur dark:border-neutral-700 dark:bg-neutral-900/90 dark:text-neutral-100">
      {/* 3D picking toggle — gates scene clicks to avoid accidental selection */}
      <div className="space-y-1">
        <button
          onClick={() => setEditing(!editing)}
          className={`w-full rounded-md px-2 py-1.5 text-sm font-medium ${
            editing
              ? 'bg-green-600 text-white hover:bg-green-500'
              : 'border border-neutral-300 text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800'
          }`}
        >
          {editing ? '● 3D picking: ON' : '○ 3D picking: OFF'}
        </button>
        <p className="text-[11px] text-neutral-500">
          {editing
            ? 'Click markers / walls in the 3D view to assign.'
            : 'Scene clicks navigate only. Right-click a marker to manage.'}
        </p>
      </div>

      {/* Systems */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <p className={label}>Systems ({groups.length})</p>
          <button onClick={addGroup} className="text-xs text-blue-600 hover:underline dark:text-blue-400">
            + Add
          </button>
        </div>
        <div className="space-y-1">
          {groups.map((g, i) => {
            const res = byGroup[g.id]
            const isActive = g.id === active.id
            return (
              <div
                key={g.id}
                className={`flex items-center gap-2 rounded border px-2 py-1 ${
                  isActive
                    ? 'border-neutral-400 bg-neutral-100 dark:border-neutral-500 dark:bg-neutral-800'
                    : 'border-neutral-200 dark:border-neutral-800'
                }`}
              >
                <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: g.color }} />
                <button onClick={() => setActive(g.id)} className="min-w-0 flex-1 text-left">
                  <p className="truncate text-xs font-medium">System {i + 1}</p>
                  <p className="truncate text-[11px] text-neutral-500 dark:text-neutral-400">
                    {g.source ? g.source.label : 'no source'} → {g.targets.length}
                    {res && ` · ${res.total_length_m.toFixed(1)} m`}
                  </p>
                </button>
                <button onClick={() => removeGroup(g.id)} className="text-neutral-500 hover:text-red-500 dark:hover:text-red-400">
                  ✕
                </button>
              </div>
            )
          })}
        </div>
      </div>

      <hr className="border-neutral-200 dark:border-neutral-800" />

      {/* Active system editor */}
      <p className="text-xs font-medium text-neutral-600 dark:text-neutral-300">
        Editing System {groups.findIndex((g) => g.id === active.id) + 1}
      </p>

      <Seg
        value={pickMode}
        onChange={setPickMode}
        options={[
          { v: 'source', label: 'Source' },
          { v: 'target', label: 'Target' },
        ]}
      />
      <Seg
        value={active.mode}
        onChange={(m) => setMode(active.id, m)}
        options={[
          { v: 'trunk', label: 'Trunk' },
          { v: 'independent', label: 'Independent' },
        ]}
      />

      <div className="space-y-1">
        <p className={label}>Source</p>
        {active.source ? (
          <div className="flex items-center justify-between rounded bg-green-600/20 px-2 py-1 text-xs">
            <span className="truncate">
              {active.source.kind}: {active.source.label}
            </span>
            <button onClick={() => clearSource(active.id)} className={chipX}>
              ✕
            </button>
          </div>
        ) : (
          <p className="text-xs text-neutral-500">none — pick a source</p>
        )}
      </div>

      <div className="space-y-1">
        <p className={label}>Targets ({active.targets.length})</p>
        <div className="max-h-20 space-y-1 overflow-auto">
          {active.targets.map((t, i) => (
            <div
              key={`${t.id ?? 'pt'}-${i}`}
              className="flex items-center justify-between rounded bg-blue-600/20 px-2 py-1 text-xs"
            >
              <span className="truncate">
                {t.kind}: {t.label}
              </span>
              <button onClick={() => removeTarget(active.id, i)} className={chipX}>
                ✕
              </button>
            </div>
          ))}
          {active.targets.length === 0 && <p className="text-xs text-neutral-500">none</p>}
        </div>
      </div>

      <div className="flex min-h-28 flex-1 flex-col gap-1">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search terminals / rooms"
          className="rounded border border-neutral-300 bg-white px-2 py-1 text-xs outline-none dark:border-neutral-700 dark:bg-neutral-800"
        />
        <ul className="min-h-0 flex-1 divide-y divide-neutral-200 overflow-auto rounded border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
          {items.map((it) => (
            <li key={`${it.kind}-${it.id}`}>
              <button
                onClick={() => pick(it)}
                className="flex w-full items-center gap-2 px-2 py-1 text-left text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800"
              >
                <span className={it.kind === 'terminal' ? 'text-amber-500 dark:text-amber-400' : 'text-cyan-600 dark:text-cyan-400'}>
                  {it.kind === 'terminal' ? '◈' : '▢'}
                </span>
                <span className="truncate">{it.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {activeResult && (
        <div className="space-y-0.5 rounded border border-neutral-300 bg-neutral-100/60 p-2 text-xs dark:border-neutral-700 dark:bg-neutral-800/60">
          <p className="text-neutral-700 dark:text-neutral-300">
            {activeResult.total_length_m.toFixed(2)} m · {activeResult.segments.length} segment(s)
          </p>
          {activeResult.unreachable_targets.length > 0 && (
            <p className="text-amber-600 dark:text-amber-400">{activeResult.unreachable_targets.length} unreachable</p>
          )}
          <a
            href={api.meshUrl(activeResult.route_id)}
            download
            className="inline-block text-blue-600 hover:underline dark:text-blue-400"
          >
            Download pipe.glb
          </a>
        </div>
      )}

      <button
        onClick={() => submitAll.mutate()}
        disabled={completeCount === 0 || submitAll.isPending}
        className="rounded-md bg-blue-600 px-2 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-40"
      >
        {submitAll.isPending ? 'Routing…' : `Route all (${completeCount})`}
      </button>

      {apartmentsQ.data && apartmentsQ.data.length > 0 && (
        <button
          onClick={() => {
            clearResults()
            loadApartments(apartmentsQ.data!)
            submitAll.mutate()
          }}
          disabled={submitAll.isPending}
          className="rounded-md border border-purple-400 bg-purple-600/10 px-2 py-1.5 text-sm font-medium text-purple-700 hover:bg-purple-600/20 disabled:opacity-40 dark:border-purple-500 dark:text-purple-300"
          title="Auto-discover apartments (Flur → reachable rooms, stopped at fire-rated walls) and route one shared trunk per apartment."
        >
          Route apartments ({apartmentsQ.data.length})
        </button>
      )}
      {submitAll.error && (
        <p className="text-xs text-red-600 dark:text-red-400">
          {submitAll.error instanceof ApiError && submitAll.error.status === 409
            ? 'Floor not prepared.'
            : `Route failed: ${(submitAll.error as Error).message}`}
        </p>
      )}

      <button
        onClick={() => {
          reset()
          clearResults()
        }}
        className="rounded-md border border-neutral-300 px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
      >
        Reset all
      </button>
    </div>
  )
}
