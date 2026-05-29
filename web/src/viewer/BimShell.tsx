import { useLayoutEffect } from 'react'
import { useGLTF } from '@react-three/drei'
import { Mesh, MeshStandardMaterial } from 'three'
import type { Walls } from '@/api/types'
import { colorFor, type Scale } from './colors'

// Loads the per-element building shell glTF and recolours each mesh by the
// active colour Scale. Mesh names are IFC GlobalIds; trimesh may suffix split
// meshes as `<id>_1`, so we fall back to the stripped id.
export function BimShell({ url, walls, scale }: { url: string; walls?: Walls; scale: Scale }) {
  const { scene } = useGLTF(url)

  useLayoutEffect(() => {
    scene.traverse((o) => {
      if (!(o instanceof Mesh)) return
      const attr = walls ? (walls[o.name] ?? walls[o.name.replace(/_\d+$/, '')]) : undefined
      o.material = new MeshStandardMaterial({
        color: colorFor(attr, scale),
        metalness: 0.05,
        roughness: 0.85,
      })
    })
  }, [scene, walls, scale])

  return <primitive object={scene} />
}
