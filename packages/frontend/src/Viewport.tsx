import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { Mesh } from "three";
import { fetchMesh } from "./api";
import type { MeshData } from "./types";

// Read-only viewport rendering the REAL build123d bracket (plate thickness = skin), re-fetched on
// change (debounced ~ regen-on-release). Geometry is driven only by parameters — no mesh editing.
function Bracket({ skinMm, holeDiaMm, widthMm, depthMm }: { skinMm: number; holeDiaMm: number; widthMm: number; depthMm: number }) {
  const ref = useRef<Mesh>(null);
  const [mesh, setMesh] = useState<MeshData | null>(null);

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      fetchMesh(skinMm, holeDiaMm, widthMm, depthMm)
        .then((d) => !cancelled && setMesh(d))
        .catch(() => {});
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [skinMm, holeDiaMm, widthMm, depthMm]);

  const geom = useMemo(() => {
    if (!mesh) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
    g.setIndex(mesh.indices);
    g.computeVertexNormals();
    g.center();
    return g;
  }, [mesh]);

  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.z += dt * 0.25;
  });

  if (!geom) return null;
  return (
    <mesh ref={ref} geometry={geom} scale={0.05} rotation={[-Math.PI / 2, 0, 0]}>
      <meshStandardMaterial color="#4a9eff" metalness={0.1} roughness={0.55} side={THREE.DoubleSide} />
    </mesh>
  );
}

export function Viewport({ skinMm, holeDiaMm, widthMm, depthMm }: { skinMm: number; holeDiaMm: number; widthMm: number; depthMm: number }) {
  return (
    <Canvas camera={{ position: [3.5, 3, 4], fov: 45 }} style={{ background: "#0d1117" }}>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 8, 5]} intensity={1.2} />
      <directionalLight position={[-4, 2, -3]} intensity={0.4} />
      <Bracket skinMm={skinMm} holeDiaMm={holeDiaMm} widthMm={widthMm} depthMm={depthMm} />
      <gridHelper args={[20, 20, "#484f58", "#30363d"]} />
    </Canvas>
  );
}
