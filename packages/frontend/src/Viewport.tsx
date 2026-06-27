import { Canvas, useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Mesh } from "three";

// Read-only viewport: a bracket proxy whose plate thickness tracks the skin slider (Tier-0 preview).
// No direct mesh editing — geometry is driven only by parameters. (No drei: three built-ins only.)
function Bracket({ skinMm }: { skinMm: number }) {
  const ref = useRef<Mesh>(null);
  const thickness = Math.max(0.2, skinMm) / 5;
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += dt * 0.3;
  });
  return (
    <mesh ref={ref} position={[0, thickness / 2, 0]}>
      <boxGeometry args={[3, thickness, 2]} />
      <meshStandardMaterial color="#4a9eff" metalness={0.1} roughness={0.6} />
    </mesh>
  );
}

export function Viewport({ skinMm }: { skinMm: number }) {
  return (
    <Canvas camera={{ position: [4, 3, 5], fov: 45 }} style={{ background: "#0d1117" }}>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 8, 5]} intensity={1.1} />
      <Bracket skinMm={skinMm} />
      <gridHelper args={[20, 20, "#484f58", "#30363d"]} />
    </Canvas>
  );
}
