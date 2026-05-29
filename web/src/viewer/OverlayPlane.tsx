import { useLayoutEffect, useMemo, useRef } from 'react'
import { useTexture } from '@react-three/drei'
import { DoubleSide, Group, Matrix4, NearestFilter } from 'three'
import type { GridMeta } from '@/api/types'

// A textured plane at the routing elevation, aligned to the building via the
// site->world matrix. The PNG is georeferenced to the voxel grid (see
// ifcbox/overlays.py).
export function OverlayPlane({ grid, url, crisp }: { grid: GridMeta; url: string; crisp?: boolean }) {
  const tex = useTexture(url)
  const ref = useRef<Group>(null)

  const matrix = useMemo(() => {
    const a = grid.site_to_world // 4x4 row-major
    return new Matrix4().set(
      a[0][0], a[0][1], a[0][2], a[0][3],
      a[1][0], a[1][1], a[1][2], a[1][3],
      a[2][0], a[2][1], a[2][2], a[2][3],
      a[3][0], a[3][1], a[3][2], a[3][3],
    )
  }, [grid])

  useLayoutEffect(() => {
    if (crisp) {
      tex.magFilter = NearestFilter
      tex.needsUpdate = true
    }
  }, [tex, crisp])

  useLayoutEffect(() => {
    const g = ref.current
    if (!g) return
    g.matrixAutoUpdate = false
    g.matrix.copy(matrix)
    g.matrixWorldNeedsUpdate = true
  }, [matrix])

  const [nx, ny] = grid.shape
  const w = nx * grid.resolution
  const h = ny * grid.resolution
  const cx = grid.origin[0] + w / 2
  const cy = grid.origin[1] + h / 2

  return (
    <group ref={ref}>
      <mesh position={[cx, cy, grid.pipe_z + 0.03]}>
        <planeGeometry args={[w, h]} />
        <meshBasicMaterial map={tex} transparent depthWrite={false} side={DoubleSide} />
      </mesh>
    </group>
  )
}
