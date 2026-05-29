import { useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useAuth } from '@/state/auth'
import { useSelection } from '@/state/selection'

export function ModelsView() {
  const logout = useAuth((s) => s.logout)
  const openModel = useSelection((s) => s.openModel)
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)

  const models = useQuery({ queryKey: ['models'], queryFn: api.listModels })

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadModel(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['models'] }),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteModel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['models'] }),
  })

  return (
    <div className="flex h-full flex-col bg-neutral-50 text-neutral-900">
      <header className="flex items-center justify-between border-b border-neutral-200 bg-white px-6 py-3">
        <h1 className="text-base font-semibold">IFCBox</h1>
        <button
          onClick={logout}
          className="text-sm text-neutral-500 hover:text-neutral-900"
        >
          Sign out
        </button>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-neutral-700">Models</h2>
          <div>
            <input
              ref={fileRef}
              type="file"
              accept=".ifc"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) upload.mutate(f)
                e.target.value = ''
              }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={upload.isPending}
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50"
            >
              {upload.isPending ? 'Uploading…' : 'Upload IFC'}
            </button>
          </div>
        </div>

        {models.isLoading && <p className="text-sm text-neutral-500">Loading…</p>}
        {models.error && (
          <p className="text-sm text-red-600">Could not load models (is the API running?).</p>
        )}
        {models.data?.length === 0 && (
          <p className="text-sm text-neutral-500">No models yet — upload an IFC to start.</p>
        )}

        <ul className="divide-y divide-neutral-200 overflow-hidden rounded-md border border-neutral-200 bg-white">
          {models.data?.map((m) => (
            <li
              key={m.model_id}
              onClick={() => openModel(m.model_id)}
              className="flex cursor-pointer items-center justify-between px-4 py-3 hover:bg-neutral-50"
            >
              <div>
                <p className="text-sm font-medium">{m.filename}</p>
                <p className="text-xs text-neutral-500">
                  {m.storey_count} storeys · {m.status}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <code className="text-xs text-neutral-400">{m.model_id}</code>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (confirm(`Delete ${m.filename}?`)) remove.mutate(m.model_id)
                  }}
                  className="text-xs text-neutral-400 hover:text-red-600"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      </main>
    </div>
  )
}
