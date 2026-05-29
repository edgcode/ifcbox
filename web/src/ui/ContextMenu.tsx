import { useContextMenu } from '@/state/contextMenu'
import { sameAnchor, useRouteBuilder } from '@/state/routeBuilder'

export function ContextMenu() {
  const { anchor, x, y, close } = useContextMenu()
  const groups = useRouteBuilder((s) => s.groups)
  const activeId = useRouteBuilder((s) => s.activeId)
  const assignSource = useRouteBuilder((s) => s.assignSource)
  const appendTarget = useRouteBuilder((s) => s.appendTarget)
  const removeAnchor = useRouteBuilder((s) => s.removeAnchor)

  if (!anchor) return null

  const active = groups.find((g) => g.id === activeId)
  const sysNum = groups.findIndex((g) => g.id === activeId) + 1
  const isSource = !!active?.source && sameAnchor(active.source, anchor)
  const isTarget = !!active?.targets.some((t) => sameAnchor(t, anchor))

  const Item = ({ label, onClick }: { label: string; onClick: () => void }) => (
    <button
      onClick={() => {
        onClick()
        close()
      }}
      className="block w-full px-3 py-1.5 text-left text-xs text-neutral-100 hover:bg-neutral-700"
    >
      {label}
    </button>
  )

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={close} onContextMenu={(e) => { e.preventDefault(); close() }} />
      <div
        className="fixed z-50 min-w-44 overflow-hidden rounded-md border border-neutral-700 bg-neutral-900/95 py-1 shadow-lg backdrop-blur"
        style={{ left: x, top: y }}
      >
        <p className="truncate border-b border-neutral-800 px-3 py-1 text-[11px] text-neutral-400">
          {anchor.kind}: {anchor.label}
        </p>
        {!isSource && <Item label={`Set as source (System ${sysNum})`} onClick={() => assignSource(anchor)} />}
        {!isTarget && <Item label={`Add as target (System ${sysNum})`} onClick={() => appendTarget(anchor)} />}
        {isSource && <Item label="Clear source" onClick={() => removeAnchor(anchor)} />}
        {isTarget && <Item label="Remove target" onClick={() => removeAnchor(anchor)} />}
      </div>
    </>
  )
}
