import { useMemo } from 'react'
import { useGLTF } from '@react-three/drei'
import { Mesh, MeshStandardMaterial } from 'three'

// Renders the route pipe glTF in CHW blue. The glb is in true world coords,
// matching the shell + markers.
export function PipeNetwork({ url }: { url: string }) {
  const { scene } = useGLTF(url)
  useMemo(() => {
    scene.traverse((o) => {
      if (o instanceof Mesh) {
        o.material = new MeshStandardMaterial({
          color: '#2563eb',
          metalness: 0.2,
          roughness: 0.4,
        })
      }
    })
  }, [scene])
  return <primitive object={scene} />
}
