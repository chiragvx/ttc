import { Canvas, type ThreeEvent } from "@react-three/fiber";
import { Bounds, OrbitControls, useBounds } from "@react-three/drei";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { Mesh } from "three";
import { fetchMesh, fetchMeshFeatures, type InstanceRow } from "./api";
import { FeatureCard } from "./FeatureCard";
import type { MeshData, PickableFeature } from "./types";

// A hover marker's radius in raw backend mm — matches the 15mm auto-layout gap already used
// elsewhere (packages/subsystems/assembly.py) as a "typical component scale", not derived from the
// actual part's own size (we don't have per-instance mesh segmentation to measure that from).
const HOVER_MARKER_RADIUS_MM = 15;

const SCALE = 0.05;
const ROTATION_X = -Math.PI / 2;
// how much the part's largest bounding-box dimension has to change (grow or shrink) before we
// auto-refit the camera — small slider tweaks shouldn't yank the view around, but switching to a
// wildly differently-sized part (or instance) should.
const REFIT_RATIO = 1.5;

interface Selection {
  feature: PickableFeature;
  screenX: number;
  screenY: number;
}

// Read-only viewport rendering the REAL build123d geometry of the ACTIVE subsystem (bracket, enclosure,
// …), re-fetched whenever `refreshKey` bumps (a slider commit or a subsystem switch). Geometry is
// driven only by parameters — no mesh editing.
function Part({
  refreshKey,
  onSelect,
  onSizeChanged,
  hoverWorldOffset,
}: {
  refreshKey: number;
  onSelect: (s: Selection | null) => void;
  onSizeChanged: () => void;
  hoverWorldOffset: [number, number, number] | null;
}) {
  const ref = useRef<Mesh>(null);
  const [mesh, setMesh] = useState<MeshData | null>(null);
  const [features, setFeatures] = useState<PickableFeature[]>([]);
  // BufferGeometry.center() translates vertices by -boundingBoxCenter; features (in the SAME raw
  // backend coordinate space as mesh.positions) need that SAME subtraction before being compared
  // against a click, or they'd be offset from the geometry they're meant to describe.
  const centerOffset = useRef(new THREE.Vector3());
  const lastFitSize = useRef(0);

  // LIVE-DRAG REGEN (2026-07-19): single-flight, latest-wins — NOT a fixed debounce. `refreshKey`
  // bumps on every slider tick (~30-60/s during a drag); the OLD code waited 200ms after the LAST
  // bump then fetched once (release-only), so the 3D never moved while you dragged. Instead: keep at
  // most ONE /mesh regen in flight at a time, and the instant it returns, if `refreshKey` advanced
  // while it ran, immediately regen for the newest state. This self-paces to whatever the kernel can
  // sustain — a wedge part (~60ms full rebuild+tessellate) refreshes ~10x/s so the viewport tracks
  // the drag live; a big lofted body (~2s) refreshes as fast as it can and converges on release —
  // and it NEVER piles up N stale tessellations server-side (the failure mode that used to freeze
  // the whole backend). This respects the three-tier doctrine: the kernel is NOT in the 30Hz loop
  // (the slider + HUD run on the instant WS path); it runs one-at-a-time, opportunistically.
  const latestKey = useRef(refreshKey);
  const inFlight = useRef(false);
  // Liveness, NOT per-fetch abort. An earlier version aborted the in-flight fetch in the [refreshKey]
  // effect's CLEANUP — but that cleanup runs on EVERY refreshKey bump, not just unmount, so every
  // slider tick aborted the running fetch AND (via a `!aborted` guard) killed the .finally re-pump
  // that is the whole catch-up mechanism. Result: the moment you stopped dragging with a fetch still
  // in flight, nothing re-pumped and the viewport froze on a stale mesh until the next interaction
  // (found by the 2026-07-19 adversarial review — a real, critical regression). Fix: never abort
  // per-tick. `aliveRef` only guards setState/re-pump against a true unmount; the re-pump condition
  // no longer references any abort state, so it always fires when the key advanced mid-fetch.
  const aliveRef = useRef(true);

  const pump = useCallback(() => {
    if (inFlight.current || !aliveRef.current) return; // one running (it re-pumps if behind), or dead
    const startedKey = latestKey.current;
    inFlight.current = true;
    Promise.all([fetchMesh(), fetchMeshFeatures().catch(() => [])])
      .then(([d, f]) => {
        if (!aliveRef.current) return; // component unmounted while this was in flight
        setMesh(d);
        setFeatures(f);
      })
      .catch(() => {})
      .finally(() => {
        inFlight.current = false;
        // edits landed while this fetch was in flight → immediately regen for the newest state
        if (aliveRef.current && latestKey.current !== startedKey) pump();
      });
  }, []);

  useEffect(() => {
    latestKey.current = refreshKey;
    onSelect(null); // a geometry refresh invalidates whatever was selected on the old mesh
    pump();
    // NO cleanup here — cleanup runs on every refreshKey bump, and aborting/tearing down per-tick is
    // exactly what caused the freeze above. Unmount handling lives in its own effect below.
  }, [refreshKey, pump, onSelect]);

  // Unmount-only liveness. Set true on (re)mount so a StrictMode double-mount or a part-switch remount
  // starts alive again; false on unmount so an in-flight fetch can't setState on a dead component.
  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  const geom = useMemo(() => {
    if (!mesh || mesh.positions.length === 0) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
    g.setIndex(mesh.indices);
    g.computeVertexNormals();
    g.computeBoundingBox();
    g.boundingBox?.getCenter(centerOffset.current);
    g.center();
    return g;
  }, [mesh]);

  // Auto-refit ONLY when the part's actual size changed meaningfully (a fresh part/instance, or a
  // slider push that genuinely resized it a lot) — not on every trivial slider tweak, which would
  // otherwise yank the camera around while someone's mid-drag on an unrelated dimension.
  useEffect(() => {
    if (!geom?.boundingBox) return;
    const size = new THREE.Vector3();
    geom.boundingBox.getSize(size);
    const largest = Math.max(size.x, size.y, size.z) || 1;
    const prev = lastFitSize.current;
    if (prev === 0 || largest / prev > REFIT_RATIO || largest / prev < 1 / REFIT_RATIO) {
      lastFitSize.current = largest;
      onSizeChanged();
    }
  }, [geom]);

  // Rough click-to-select: nearest pickable feature (by WORLD-space distance) to the click point.
  // Uses the mesh's own localToWorld() so this stays correct regardless of the mesh's current
  // transform. Approximate by design: see packages/subsystems/features.py's own documented
  // limitations (no per-instance rotation correction, no nested-composite correction). Good enough
  // for "which feature did I click near," not exact face-level picking (that needs OCCT
  // topological identity — specialist-gated).
  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (!ref.current || features.length === 0) {
      onSelect(null);
      return;
    }
    let best: PickableFeature | null = null;
    let bestDist = Infinity;
    const local = new THREE.Vector3();
    const world = new THREE.Vector3();
    for (const f of features) {
      local.set(f.point[0], f.point[1], f.point[2]).sub(centerOffset.current);
      world.copy(local);
      ref.current.localToWorld(world);
      const d = world.distanceTo(e.point);
      if (d < bestDist) {
        bestDist = d;
        best = f;
      }
    }
    onSelect(best ? { feature: best, screenX: e.nativeEvent.clientX, screenY: e.nativeEvent.clientY } : null);
  };

  if (!geom) return null;
  // The hover marker sits INSIDE this mesh (a child, not a sibling) so it inherits the outer mesh's
  // scale/rotation from the Three.js scene graph automatically — same reasoning as handleClick's own
  // centerOffset subtraction, just without needing the extra localToWorld() (nothing outside this
  // mesh needs the point). raycast=null keeps it purely decorative — it must never steal a click
  // that was meant for feature-picking.
  const hoverLocal = hoverWorldOffset
    ? new THREE.Vector3(...hoverWorldOffset).sub(centerOffset.current)
    : null;
  return (
    <mesh ref={ref} geometry={geom} scale={SCALE} rotation={[ROTATION_X, 0, 0]} onClick={handleClick}>
      <meshStandardMaterial color="#4a9eff" metalness={0.1} roughness={0.55} side={THREE.DoubleSide} />
      {hoverLocal && (
        <mesh position={hoverLocal} raycast={() => null}>
          <sphereGeometry args={[HOVER_MARKER_RADIUS_MM, 20, 20]} />
          <meshBasicMaterial color="#1f6feb" transparent opacity={0.3} depthWrite={false} />
        </mesh>
      )}
    </mesh>
  );
}

// Imperatively re-fits the camera to whatever's currently inside the enclosing <Bounds> —
// triggered by Part reporting a meaningful size change, and by the manual "Fit" button.
function AutoFit({ trigger }: { trigger: number }) {
  const bounds = useBounds();
  useEffect(() => {
    if (trigger > 0) bounds.refresh().fit();
  }, [trigger]);
  return null;
}

export function Viewport({
  refreshKey,
  hoveredInstanceId,
  instances,
}: {
  refreshKey: number;
  hoveredInstanceId?: string | null;
  instances?: InstanceRow[];
}) {
  const [selection, setSelection] = useState<Selection | null>(null);
  const [autoRotate, setAutoRotate] = useState(false);
  const [fitTrigger, setFitTrigger] = useState(0);
  const requestFit = () => setFitTrigger((k) => k + 1);
  const hovered = hoveredInstanceId ? instances?.find((i) => i.id === hoveredInstanceId) : null;
  const hoverWorldOffset = hovered?.world_offset ?? null;

  return (
    <>
      <Canvas camera={{ position: [3.5, 3, 4], fov: 45 }} style={{ background: "#0d1117" }}
              onPointerMissed={() => setSelection(null)}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[5, 8, 5]} intensity={1.2} />
        <directionalLight position={[-4, 2, -3]} intensity={0.4} />
        <Bounds fit clip margin={1.3}>
          <AutoFit trigger={fitTrigger} />
          <Part refreshKey={refreshKey} onSelect={setSelection} onSizeChanged={requestFit} hoverWorldOffset={hoverWorldOffset} />
        </Bounds>
        {/* drag = orbit, scroll/pinch = zoom, right-drag (or two-finger drag) = pan */}
        <OrbitControls makeDefault enableDamping dampingFactor={0.12}
                       autoRotate={autoRotate} autoRotateSpeed={2} />
        <gridHelper args={[20, 20, "#484f58", "#30363d"]} />
        <axesHelper args={[2]} />
      </Canvas>
      <div style={toolbar}>
        <button onClick={requestFit} title="Reset view — fit the camera to the current part" style={btn}>
          ⤢ Fit
        </button>
        <button onClick={() => setAutoRotate((v) => !v)} title="Toggle auto-rotate"
                style={{ ...btn, background: autoRotate ? "#1f6feb" : "#21262d" }}>
          ↻ Rotate
        </button>
        <button
          onClick={() => {
            // orthographic 3-view blueprint (front/top/right, labelled XYZ). Open the freshly-rendered
            // PNG in a new tab; a cache-buster keeps it current after edits (the endpoint is no-store,
            // but the query param also defeats any intermediary/tab cache).
            void fetch(`/blueprint?t=${Date.now()}`)
              .then((r) => r.blob())
              .then((b) => window.open(URL.createObjectURL(b), "_blank"))
              .catch(() => {});
          }}
          title="Open an orthographic 3-view blueprint (front / top / right, labelled XYZ)"
          style={btn}
        >
          ⊞ Blueprint
        </button>
      </div>
      {selection && (
        <FeatureCard
          feature={selection.feature}
          screenX={selection.screenX}
          screenY={selection.screenY}
          onClose={() => setSelection(null)}
        />
      )}
    </>
  );
}

const toolbar: React.CSSProperties = {
  position: "absolute", left: 16, top: 16, zIndex: 5, display: "flex", gap: 6,
};
const btn: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "4px 10px", cursor: "pointer", fontSize: 12,
};
