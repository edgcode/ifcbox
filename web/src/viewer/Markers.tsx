import type { ThreeEvent } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { useRouteBuilder } from '@/state/routeBuilder'
import type { PickKind } from '@/state/routeBuilder'
import type { FloorDetail } from '@/api/types'

const BASE: Record<'terminal' | 'room', string> = {
  terminal: '#f59e0b',
  room: '#22d3ee',
}
const SOURCE = '#22c55e'
const TARGET = '#3b82f6'

function Marker(props: {
  pos: [number, number, number]
  kind: Exclude<PickKind, 'point'>
  id: string
  label: string
}) {
  const { pos, kind, id, label } = props
  const pick = useRouteBuilder((s) => s.pick)
  const isSource = useRouteBuilder((s) => {
    const g = s.groups.find((x) => x.id === s.activeId)
    return g?.source?.id === id
  })
  const isTarget = useRouteBuilder((s) => {
    const g = s.groups.find((x) => x.id === s.activeId)
    return !!g?.targets.some((t) => t.id === id)
  })

  const selected = isSource || isTarget
  const color = isSource ? SOURCE : isTarget ? TARGET : BASE[kind]
  const radius = (kind === 'terminal' ? 0.22 : 0.28) * (selected ? 1.3 : 1)

  return (
    <mesh
      position={pos}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation()
        pick({ kind, id, label })
      }}
      onPointerOver={(e) => {
        e.stopPropagation()
        document.body.style.cursor = 'pointer'
      }}
      onPointerOut={() => {
        document.body.style.cursor = 'auto'
      }}
    >
      <sphereGeometry args={[radius, 16, 16]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={selected ? 0.6 : 0.15}
      />
      {kind === 'room' && (
        <Html position={[0, 0, radius + 0.3]} center distanceFactor={14} zIndexRange={[10, 0]}>
          <div className="pointer-events-none whitespace-nowrap rounded bg-black/60 px-1 text-[10px] leading-tight text-white">
            {label}
          </div>
        </Html>
      )}
    </mesh>
  )
}

export function Markers({ floor }: { floor: FloorDetail }) {
  return (
    <>
      {floor.terminals.map((t) => (
        <Marker key={t.id} pos={t.xyz} kind="terminal" id={t.id} label={t.id} />
      ))}
      {floor.spaces.map((s) => (
        <Marker key={s.id} pos={s.centroid} kind="room" id={s.id} label={s.name} />
      ))}
    </>
  )
}
