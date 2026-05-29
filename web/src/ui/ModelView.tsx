import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useSelection } from '@/state/selection'
import { usePrepProgress } from '@/hooks/usePrepProgress'
import { ThemeToggle } from '@/ui/ThemeToggle'
import type { FloorStatus, Storey } from '@/api/types'

function OpenFloorButton({ index }: { index: number }) {
  const openFloor = useSelection((s) => s.openFloor)
  return (
    <button
      onClick={() => openFloor(index)}
      className="rounded-md bg-neutral-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
    >
      Open 3D →
    </button>
  )
}

export function ModelView({ modelId }: { modelId: string }) {
  const closeModel = useSelection((s) => s.closeModel)
  const model = useQuery({ queryKey: ['model', modelId], queryFn: () => api.getModel(modelId) })

  return (
    <div className="flex h-full flex-col bg-neutral-50 text-neutral-900 dark:bg-neutral-900 dark:text-neutral-100">
      <header className="flex items-center justify-between border-b border-neutral-200 bg-white px-6 py-3 dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex items-center gap-3">
          <button
            onClick={closeModel}
            className="text-sm text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white"
          >
            ← Models
          </button>
          <h1 className="text-base font-semibold">{model.data?.filename ?? modelId}</h1>
        </div>
        <ThemeToggle />
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 space-y-4 p-6">
        <h2 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Storeys</h2>
        {model.isLoading && <p className="text-sm text-neutral-500 dark:text-neutral-400">Loading…</p>}
        {model.error && <p className="text-sm text-red-600 dark:text-red-400">Could not load model.</p>}
        <ul className="divide-y divide-neutral-200 overflow-hidden rounded-md border border-neutral-200 bg-white dark:divide-neutral-800 dark:border-neutral-800 dark:bg-neutral-800/40">
          {model.data?.storeys.map((s) => (
            <FloorRow key={s.index} modelId={modelId} storey={s} />
          ))}
        </ul>
      </main>
    </div>
  )
}

const STATUS_LABEL: Record<FloorStatus, string> = {
  unprepared: 'Not prepared',
  preparing: 'Preparing…',
  ready: 'Ready',
  error: 'Error',
}

const STATUS_COLOR: Record<FloorStatus, string> = {
  unprepared: 'text-neutral-400',
  preparing: 'text-amber-600 dark:text-amber-400',
  ready: 'text-green-600 dark:text-green-400',
  error: 'text-red-600 dark:text-red-400',
}

function FloorRow({ modelId, storey }: { modelId: string; storey: Storey }) {
  const qc = useQueryClient()
  const floor = useQuery({
    queryKey: ['floor', modelId, storey.index],
    queryFn: () => api.floorDetail(modelId, storey.index),
  })
  const status: FloorStatus = floor.data?.status ?? 'unprepared'

  const prepare = useMutation({
    mutationFn: () => api.prepareFloor(modelId, storey.index),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['floor', modelId, storey.index] }),
  })

  const progress = usePrepProgress(modelId, storey.index, status === 'preparing')

  return (
    <li className="px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">
            {storey.index} · {storey.name}
          </p>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">elev {storey.elevation.toFixed(2)} m</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-xs font-medium ${STATUS_COLOR[status]}`}>
            {STATUS_LABEL[status]}
          </span>
          {(status === 'unprepared' || status === 'error') && (
            <button
              onClick={() => prepare.mutate()}
              disabled={prepare.isPending}
              className="rounded-md bg-neutral-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
            >
              Prepare
            </button>
          )}
          {status === 'ready' && floor.data && (
            <OpenFloorButton index={storey.index} />
          )}
        </div>
      </div>

      {status === 'preparing' && (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded bg-neutral-200 dark:bg-neutral-700">
            <div
              className="h-full bg-amber-500 transition-all"
              style={{ width: `${progress?.pct ?? 5}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{progress?.stage ?? 'starting…'}</p>
        </div>
      )}
      {status === 'error' && floor.data && (
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">prep failed — retry</p>
      )}
    </li>
  )
}
