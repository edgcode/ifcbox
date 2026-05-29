import { useMemo } from 'react'
import { useGLTF } from '@react-three/drei'
import { Mesh, MeshStandardMaterial } from 'three'

// Renders a route pipe glTF in the given colour. The glb is in true world
// coords, matching the shell + markers.
export function PipeNetwork({ url, color }: { url: string; color: string }) {
  const { scene } = useGLTF(url)
  useMemo(() => {
    scene.traverse((o) => {
      if (o instanceof Mesh) {
        o.material = new MeshStandardMaterial({ color, metalness: 0.2, roughness: 0.4 })
      }
    })
  }, [scene, color])
  return <primitive object={scene} />
}
