import { useEffect } from 'react'
import { useThree } from '@react-three/fiber'
import { Plane, Vector3 } from 'three'

// Global section clip: when enabled, hide everything above `height` (world Z),
// so you can see into the floor from above. Renderer-level clipping applies to
// all materials without per-material setup.
export function Clipping({ enabled, height }: { enabled: boolean; height: number }) {
  const gl = useThree((s) => s.gl)
  useEffect(() => {
    gl.clippingPlanes = enabled ? [new Plane(new Vector3(0, 0, -1), height)] : []
    return () => {
      gl.clippingPlanes = []
    }
  }, [gl, enabled, height])
  return null
}
