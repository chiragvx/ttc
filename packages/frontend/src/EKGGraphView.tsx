import type { LedgerGraphData } from "./types";

// A read-only topology view of the design's INSTANCE graph — nodes are `ledger.instances`, edges are
// `ledger.connections` (typed interface<->interface mates) and `ledger.couplings` (derived-load
// edges). Distinct from Viewport.tsx's 3D geometry viewport: this is a 2D SVG diagram of the
// ENGINEERING GRAPH itself, not the built solid. PURELY PRESENTATIONAL — ledger data + a click
// callback in, nothing else; no fetching, no App-level state, no graph-viz library (plain SVG with a
// simple deterministic circular layout, matching packages/frontend/CLAUDE.md's "read-only viewport,
// no new deps" spirit and the RequirementsCard/ManufacturingCard presentational-card pattern).
//
// Dangling references are a REAL, expected case here, not a bug to guard against defensively as an
// afterthought: packages/subsystems/placement.py::connection_issues() exists specifically because a
// Connection/Coupling endpoint can reference an instance_id that no longer exists (e.g. the part was
// removed after the edge was authored). This component must degrade gracefully on exactly that case
// — skip the unresolved edge, never crash the render.
export interface EKGGraphViewProps {
  ledger: LedgerGraphData | null; // null while loading — render a loading/empty state
  selectedInstanceId?: string | null;
  onSelectInstance: (instanceId: string) => void;
}

const NODE_R = 26;
const MARGIN = 90; // room for the label text + selection ring around the outermost nodes

interface LayoutResult {
  positions: Record<string, { x: number; y: number }>;
  size: number;
}

// Evenly space `n` nodes around a circle of radius proportional to `n`, centered in the viewBox.
// Pure function of the instance ids (sorted, so layout never depends on backend key-insertion order)
// — same ledger in always produces the same picture out.
function layoutCircular(ids: string[]): LayoutResult {
  const n = ids.length;
  const radius = Math.max(120, n * 30);
  const size = radius * 2 + MARGIN * 2;
  const center = size / 2;
  const positions: Record<string, { x: number; y: number }> = {};
  ids.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2; // first node at 12 o'clock
    positions[id] = { x: center + radius * Math.cos(angle), y: center + radius * Math.sin(angle) };
  });
  return { positions, size };
}

interface ResolvedEdge {
  key: string;
  x1: number; y1: number; x2: number; y2: number;
  label: string;
  kind: "connection" | "coupling";
}

export function EKGGraphView({ ledger, selectedInstanceId, onSelectInstance }: EKGGraphViewProps) {
  // Defense in depth beyond the `ledger === null` case: getLedger() now checks res.ok (2026-07-19
  // review, CRITICAL — an unchecked 401/503 error body used to reach here as a truthy-but-malformed
  // object and crash on Object.keys(undefined), with no ErrorBoundary anywhere to contain it), but a
  // component that's handed ledger data shouldn't ALSO assume every sub-field is always present.
  const ids = ledger?.instances ? Object.keys(ledger.instances).sort() : [];

  if (!ledger || !ledger.instances || ids.length === 0) {
    return (
      <div style={emptyState}>
        No parts yet — ask the copilot to build something
      </div>
    );
  }

  const { positions, size } = layoutCircular(ids);

  // Nodes actually touched by a RESOLVED edge (both endpoints exist) are "connected" for styling
  // purposes — an edge that gets skipped for a dangling endpoint doesn't count as touching the end
  // that DID resolve, since nothing is actually drawn to it.
  const touched = new Set<string>();

  const connectionEdges: ResolvedEdge[] = [];
  for (const c of ledger.connections ?? []) {
    const pa = positions[c.a.instance_id];
    const pb = positions[c.b.instance_id];
    if (!pa || !pb) continue; // dangling endpoint(s) — skip, don't crash (placement.py::connection_issues' DANGLING case)
    touched.add(c.a.instance_id);
    touched.add(c.b.instance_id);
    connectionEdges.push({
      key: `conn-${c.id}`,
      x1: pa.x, y1: pa.y, x2: pb.x, y2: pb.y,
      label: `${c.kind}: ${c.a.interface}<->${c.b.interface}`,
      kind: "connection",
    });
  }

  const couplingEdges: ResolvedEdge[] = [];
  for (const cpl of ledger.couplings ?? []) {
    const target = positions[cpl.target_instance];
    // The target is "touched" (legitimately part of the graph) whenever IT resolves, independent of
    // whether any input happens to be instance-sourced — a coupling with only literal-value inputs
    // (a real, valid case: packages/ledger/schema.py::CouplingInput's "value" form) still legitimately
    // targets a real part (2026-07-19 review, HIGH — this used to live inside the input loop below,
    // gated on `input.from_instance` existing, so an all-literal-inputs coupling never marked its own
    // resolvable target as touched).
    if (target) touched.add(cpl.target_instance);
    let i = 0;
    for (const input of Object.values(cpl.inputs ?? {})) {
      if (!input.from_instance) continue; // a literal-value input has no source instance to draw from
      const src = positions[input.from_instance];
      if (!src) continue; // dangling from_instance — skip just this edge, not the whole coupling
      // The source is "touched" whenever IT resolves, independent of whether the TARGET also resolves
      // — an unrelated dangling target elsewhere in the same coupling must not falsely disconnect-flag
      // a perfectly valid source node (2026-07-19 review, MEDIUM — this used to sit after a `continue`
      // keyed on the target, so a dangling target discarded every one of its inputs' touched-marking
      // too, even a fully-valid one).
      touched.add(input.from_instance);
      if (!target) continue; // nowhere to draw the edge TO, but the source above is still marked touched
      couplingEdges.push({
        key: `cpl-${cpl.id}-${i++}`,
        x1: src.x, y1: src.y, x2: target.x, y2: target.y,
        label: cpl.relation,
        kind: "coupling",
      });
    }
  }

  return (
    <div style={{ width: "100%" }} data-testid="ekg-graph-view">
      <svg
        data-testid="ekg-graph-svg"
        viewBox={`0 0 ${size} ${size}`}
        width="100%"
        style={{ display: "block", background: "#0d1117", borderRadius: 10, border: "1px solid #30363d" }}
      >
        {connectionEdges.map((e) => <Edge key={e.key} edge={e} />)}
        {couplingEdges.map((e) => <Edge key={e.key} edge={e} />)}

        {ids.map((id) => {
          const p = positions[id];
          const inst = ledger.instances[id];
          const isSelected = selectedInstanceId != null && id === selectedInstanceId;
          const isDisconnected = !touched.has(id);
          return (
            <g
              key={id}
              data-testid={`ekg-node-${id}`}
              data-selected={isSelected}
              data-disconnected={isDisconnected}
              onClick={() => onSelectInstance(id)}
              style={{ cursor: "pointer" }}
            >
              {isSelected && (
                <circle cx={p.x} cy={p.y} r={NODE_R + 6} fill="none" stroke="#58a6ff" strokeWidth={3} />
              )}
              <circle
                cx={p.x} cy={p.y} r={NODE_R}
                fill="#161b22"
                stroke={isDisconnected ? "#d29922" : "#30363d"}
                strokeWidth={isDisconnected ? 2 : 1.5}
                strokeDasharray={isDisconnected ? "4 3" : undefined}
              />
              <text x={p.x} y={p.y - 2} textAnchor="middle" fontSize={10} fill="#c9d1d9">{id}</text>
              <text x={p.x} y={p.y + 10} textAnchor="middle" fontSize={8} fill="#8b949e">{inst.subsystem_type}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Edge({ edge }: { edge: ResolvedEdge }) {
  const isConnection = edge.kind === "connection";
  const mx = (edge.x1 + edge.x2) / 2;
  const my = (edge.y1 + edge.y2) / 2;
  return (
    <g data-testid={`ekg-edge-${edge.key}`}>
      <line
        x1={edge.x1} y1={edge.y1} x2={edge.x2} y2={edge.y2}
        stroke={isConnection ? "#58a6ff" : "#3fb950"}
        strokeWidth={1.5}
        strokeDasharray={isConnection ? undefined : "6 3"}
      />
      <text x={mx} y={my} textAnchor="middle" fontSize={8} fill="#8b949e">{edge.label}</text>
    </g>
  );
}

const emptyState: React.CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center", minHeight: 200,
  padding: "12px 14px", border: "1px solid #30363d", borderRadius: 10, background: "#161b22",
  color: "#8b949e", fontSize: 12, textAlign: "center",
};
