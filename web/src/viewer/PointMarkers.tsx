import type { ThreeEvent } from '@react-three/fiber'
import { useRouteBuilder } from '@/state/routeBuilder'
import type { AnchorSel } from '@/state/routeBuilder'
import { useContextMenu } from '@/state/contextMenu'

const SOURCE = '#22c55e'
const TARGET = '#3b82f6'

// Diamonds marking picked free points (PointAnchors) across all systems, so a
// clicked spot that isn't a terminal/room is visible before routing.
export function PointMarkers() {
  const groups = useRouteBuilder((s) => s.groups)
  const openMenu = useContextMenu((s) => s.open)

  const pts: { anchor: AnchorSel; color: string; key: string }[] = []
  for (const g of groups) {
    if (g.source?.kind === 'point' && g.source.xyz) {
      pts.push({ anchor: g.source, color: SOURCE, key: `${g.id}-src` })
    }
    g.targets.forEach((t, i) => {
      if (t.kind === 'point' && t.xyz) {
        pts.push({ anchor: t, color: TARGET, key: `${g.id}-t${i}` })
      }
    })
  }

  return (
    <>
      {pts.map((p) => (
        <mesh
          key={p.key}
          position={p.anchor.xyz!}
          onContextMenu={(e: ThreeEvent<MouseEvent>) => {
            e.stopPropagation()
            e.nativeEvent.preventDefault()
            openMenu(p.anchor, e.nativeEvent.clientX, e.nativeEvent.clientY)
          }}
        >
          <octahedronGeometry args={[0.3]} />
          <meshStandardMaterial color={p.color} emissive={p.color} emissiveIntensity={0.5} />
        </mesh>
      ))}
    </>
  )
}
