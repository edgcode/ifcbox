import { useGLTF } from '@react-three/drei'

// Loads the server-generated per-floor building shell (glTF, world coords, Z-up).
// NOTE: useGLTF fetches without our X-App-Token header; fine while auth is off.
// When auth (deploy D-3) lands, switch to an authed blob-URL loader.
export function BimShell({ url }: { url: string }) {
  const { scene } = useGLTF(url)
  return <primitive object={scene} />
}
