import { useCallback, useEffect, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { LedgerGraphData } from "./types";

// A read-only topology view of the design's INSTANCE graph — nodes are `ledger.instances`, edges are
// `ledger.connections` (typed interface<->interface mates, optionally decorated by a
// `ledger.join_annotations` entry attached via `connection_id` — see edgeStyleFor), `ledger.couplings`
// (derived-load edges), and `ledger.fit_bindings` (2026-07-27, derived-dimension edges: connector <-
// host). Distinct from
// Viewport.tsx's 3D geometry viewport: this is a 2D diagram of the ENGINEERING
// GRAPH itself, not the built solid. PURELY PRESENTATIONAL — ledger data + a click callback in,
// nothing else; no fetching, no App-level state.
//
// Rebuilt (2026-07-19) on @xyflow/react for a real "Figma-style" node-graph — draggable cards,
// curved directional connectors, pan/zoom, minimap — replacing the old hand-rolled plain-SVG
// circular-layout version. See computeGraphData()/mergeNodePositions() below for the load-bearing
// logic carried forward from that version (dangling-reference skip, disconnected-flag rules,
// drag-position preservation across ledger refreshes).
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

// --- pure graph-data computation (constraint 4) ------------------------------------------------
// ZERO React/xyflow imports below this point up to the component — this is what gets unit-tested
// directly (fast, reliable, no jsdom/ResizeObserver involved), matching this codebase's established
// "extract the risky pure logic, test it directly" pattern (see
// packages/agents/openrouter_provider.py::_looks_truncated).

export interface EKGParamEntry {
  key: string;
  value: number;
  unit: string;
}
export interface EKGComputedNode {
  id: string;
  subsystemType: string;
  disconnected: boolean;
  // True whenever this instance is the target of at least one Coupling, REGARDLESS of whether an
  // edge got drawn to it. 2026-07-27: a coupling with only literal-value inputs (e.g. a stated
  // mass_g/accel_g load with no from_instance) legitimately has no source to draw a line FROM, so it
  // was previously invisible in the graph -- the ledger had the load, the viewer showed nothing. This
  // is a small on-node marker for that case, independent of the edge-drawing logic above.
  hasCoupling: boolean;
  params: EKGParamEntry[];
}
export interface EKGComputedEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  kind: "connection" | "coupling" | "fit";
  // The underlying Connection.kind ("mate" | "bolted" | "slip_fit" | "containment") -- only set for
  // kind === "connection" edges (of this three-member union). 2026-07-22: previously kind was only
  // ever shown as plain text in the edge label, with zero visual distinction -- this is what lets
  // the graph itself communicate the relationship type (a rigid bolted join vs. an intentional
  // containment) at a glance.
  connectionKind?: string;
  // True when a `JoinAnnotation` (packages/ledger/schema.py) targets this edge's underlying Connection
  // via `connection_id` -- only ever set for kind === "connection" edges, the same restriction as
  // connectionKind above (a JoinAnnotation is BOM/documentation-grade "how joined" data attached to an
  // EXISTING Connection; it has no analog on a Coupling or FitBinding). 2026-08-01: lets edgeStyleFor
  // show, at a glance, which joins have a recorded real-world fastening method (bolted/press_fit/
  // welded/adhesive/custom) vs. which are still just a bare geometric mate.
  hasJoinAnnotation?: boolean;
}

export function computeGraphData(ledger: LedgerGraphData): { nodes: EKGComputedNode[]; edges: EKGComputedEdge[] } {
  const instances = ledger.instances ?? {};
  const ids = Object.keys(instances).sort();

  // Nodes actually touched by a RESOLVED edge (both endpoints exist) are "connected" for styling
  // purposes — an edge that gets skipped for a dangling endpoint doesn't count as touching the end
  // that DID resolve, since nothing is actually drawn to it.
  const touched = new Set<string>();
  const coupledTargets = new Set<string>(); // resolvable Coupling.target_instance ids -- see EKGComputedNode.hasCoupling
  const edges: EKGComputedEdge[] = [];

  // 2026-08-01 -- Connection ids carrying a JoinAnnotation, for the connection loop below. A
  // JoinAnnotation references its Connection by id (never a standalone instance-to-instance record —
  // see JoinAnnotation's own docstring), so this is a simple id-membership check, not another
  // instance-existence lookup. An annotation whose `connection_id` matches no real Connection (e.g.
  // the connection was later removed) simply never matches here -- silently inert, same
  // dangling-reference posture as every other edge kind in this file, not a crash.
  const annotatedConnectionIds = new Set((ledger.join_annotations ?? []).map((ja) => ja.connection_id));

  for (const c of ledger.connections ?? []) {
    if (!instances[c.a.instance_id] || !instances[c.b.instance_id]) continue; // dangling endpoint(s) — skip, don't crash (placement.py::connection_issues' DANGLING case)
    touched.add(c.a.instance_id);
    touched.add(c.b.instance_id);
    edges.push({
      id: `conn-${c.id}`,
      source: c.a.instance_id,
      target: c.b.instance_id,
      label: `${c.kind}: ${c.a.interface}<->${c.b.interface}`,
      kind: "connection",
      connectionKind: c.kind,
      hasJoinAnnotation: annotatedConnectionIds.has(c.id),
    });
  }

  for (const cpl of ledger.couplings ?? []) {
    const targetResolves = !!instances[cpl.target_instance];
    // The target is "touched" (legitimately part of the graph) whenever IT resolves, independent of
    // whether any input happens to be instance-sourced — a coupling with only literal-value inputs
    // (a real, valid case: packages/ledger/schema.py::CouplingInput's "value" form) still legitimately
    // targets a real part (2026-07-19 review, HIGH — this used to live inside the input loop below,
    // gated on `input.from_instance` existing, so an all-literal-inputs coupling never marked its own
    // resolvable target as touched).
    if (targetResolves) {
      touched.add(cpl.target_instance);
      coupledTargets.add(cpl.target_instance);
    }

    let i = 0;
    for (const input of Object.values(cpl.inputs ?? {})) {
      if (!input.from_instance) continue; // a literal-value input has no source instance to draw from
      if (!instances[input.from_instance]) continue; // dangling from_instance — skip just this edge, not the whole coupling
      // The source is "touched" whenever IT resolves, independent of whether the TARGET also resolves
      // — an unrelated dangling target elsewhere in the same coupling must not falsely disconnect-flag
      // a perfectly valid source node (2026-07-19 review, MEDIUM — this used to sit after a `continue`
      // keyed on the target, so a dangling target discarded every one of its inputs' touched-marking
      // too, even a fully-valid one).
      touched.add(input.from_instance);
      if (!targetResolves) continue; // nowhere to draw the edge TO, but the source above is still marked touched
      edges.push({
        id: `cpl-${cpl.id}-${i++}`,
        source: input.from_instance,
        target: cpl.target_instance,
        label: cpl.relation,
        kind: "coupling",
      });
    }
  }

  // 2026-07-27 — fit bindings: unlike a Coupling, a FitBinding has no literal-only-input form (both
  // connector_instance and host_instance are always real instances at wire time), so this mirrors
  // the CONNECTION loop's symmetric "both resolve or skip entirely" handling, not the coupling loop's
  // asymmetric one. Directional like a coupling edge (value flows FROM the host's cross-section INTO
  // the connector's derived dimension), so source = host, target = connector.
  for (const fb of ledger.fit_bindings ?? []) {
    if (!instances[fb.host_instance] || !instances[fb.connector_instance]) continue; // dangling endpoint(s) — skip, don't crash
    touched.add(fb.host_instance);
    touched.add(fb.connector_instance);
    edges.push({
      id: `fit-${fb.id}`,
      source: fb.host_instance,
      target: fb.connector_instance,
      label: "fit",
      kind: "fit",
    });
  }

  const nodes: EKGComputedNode[] = ids.map((id) => {
    const paramsRecord = instances[id].params ?? {};
    const params: EKGParamEntry[] = Object.keys(paramsRecord)
      .sort()
      .map((key) => ({ key, value: paramsRecord[key].value, unit: paramsRecord[key].unit }));
    return {
      id,
      subsystemType: instances[id].subsystem_type,
      disconnected: !touched.has(id),
      hasCoupling: coupledTargets.has(id),
      params,
    };
  });

  return { nodes, edges };
}

// --- layout + position-preservation merge (constraint 5) ---------------------------------------

interface XY {
  x: number;
  y: number;
}

// Evenly space `n` ids around a circle of radius proportional to `n`. Pure function of the instance
// ids (sorted upstream by computeGraphData, so layout never depends on backend key-insertion order)
// — same ledger in always produces the same picture out. Adapted from the old SVG version's
// layoutCircular(): coordinates are now centered on (0,0) (xyflow's `fitView` frames the canvas, so
// no viewBox/margin bookkeeping is needed here).
function layoutCircular(ids: string[]): Record<string, XY> {
  const n = ids.length;
  const radius = Math.max(120, n * 30);
  const positions: Record<string, XY> = {};
  ids.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2; // first node at 12 o'clock
    positions[id] = { x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
  });
  return positions;
}

export interface EKGNodeData extends Record<string, unknown> {
  subsystemType: string;
  disconnected: boolean;
  selected: boolean;
  hasCoupling: boolean;
  params: EKGParamEntry[];
}
export type EKGFlowNode = Node<EKGNodeData, "ekgCard">;

// THE point of "draggable": merge freshly computed graph data into the EXISTING @xyflow node state
// instead of replacing it, so a ledger refresh (a chat turn added/changed something) doesn't silently
// snap a user-dragged node back to its auto-layout position. An id already present in `prevNodes`
// KEEPS its current (possibly dragged) x/y — only its `data` (disconnected/selected) refreshes. A
// genuinely new id gets a fresh position from the deterministic circular layout above. An id no
// longer present in `computedNodes` simply doesn't appear in the returned array (dropped).
//
// Kept as its own function (constraint 5) so it can be unit-tested directly by mocking the
// position-bearing `prevNodes` array, rather than asserting on real pixel coordinates through jsdom
// (which has no real layout engine).
export function mergeNodePositions(
  prevNodes: EKGFlowNode[],
  computedNodes: EKGComputedNode[],
  selectedInstanceId?: string | null,
): EKGFlowNode[] {
  const prevById = new Map(prevNodes.map((n) => [n.id, n]));
  const freshLayout = layoutCircular(computedNodes.map((n) => n.id));

  return computedNodes.map((cn) => {
    const prev = prevById.get(cn.id);
    const data = {
      subsystemType: cn.subsystemType,
      disconnected: cn.disconnected,
      selected: selectedInstanceId != null && cn.id === selectedInstanceId,
      hasCoupling: cn.hasCoupling,
      params: cn.params,
    };
    // Spread `...prev` (2026-07-19 review, LOW) — a bare `{id, type, position, data}` literal here
    // drops every xyflow-OWNED field (measured, dragging, internal selected/z) the library itself
    // writes onto these controlled node objects via its own onNodesChange (see applyNodeChanges/
    // adoptUserNodes in @xyflow/react's internals). Returning a brand-new object on every merge — even
    // for a node whose position/data didn't actually change — fails xyflow's referential-identity
    // check and forces an unnecessary re-measure pass (visible edge/handle-anchor flicker) on every
    // trigger, including a plain node-selection click. Preserving the rest of `prev` and only
    // overwriting what this function actually owns (position, data) avoids that.
    if (prev) return { ...prev, position: prev.position, data };
    return { id: cn.id, type: "ekgCard" as const, position: freshLayout[cn.id], data };
  });
}

// --- custom node ("card") — constraint 6 --------------------------------------------------------
// Matches ManufacturingCard.tsx/RequirementsCard.tsx's dark palette EXACTLY: background #161b22,
// border #30363d, text #c9d1d9 primary / #8b949e secondary. Disconnected -> dashed amber border
// (#d29922), mirroring the old implementation's treatment (same color, same dashed style, now
// applied to a card instead of a circle). Selected -> a distinct blue (#58a6ff) ring, layered
// independently of the disconnected border so a node that is BOTH selected and disconnected shows
// both stylings at once (neither silently overrides the other).
// How many params to show directly on the card before collapsing the rest into a "+N more" line —
// bounds card height for a heavily-parameterized subsystem instead of letting it grow unbounded.
const _MAX_VISIBLE_PARAMS = 6;

// ParameterDef.value is a float (packages/ledger/parameter.py) — round for display so e.g. 85.00000001
// mm (an FP artifact from an earlier derived edit) doesn't render as noise; toFixed(2) then re-parse
// through Number() to also drop trailing zeros (1.50 -> "1.5", 85.00 -> "85").
function formatParamValue(value: number): string {
  return Number(value.toFixed(2)).toString();
}

// Pure, unit-testable edge styling (2026-07-22) — Couplings stay dashed green (unchanged). A
// Connection's stroke now varies by its `Connection.kind` (previously kind was only ever text in
// the label, cosmetically identical for every kind) so the relationship type is visible at a
// glance: `containment` (intentional nesting, e.g. a board inside an enclosure) gets a distinct
// dotted purple so it reads as deliberately different from a rigid join; `bolted` gets a solid
// amber (a fastened, load-bearing join); `slip_fit` gets a thin dashed teal (a designed clearance
// fit); `mate` (the default, generic touch) keeps the original solid blue baseline.
const _CONNECTION_KIND_STYLE: Record<string, React.CSSProperties> = {
  containment: { stroke: "#a371f7", strokeWidth: 1.5, strokeDasharray: "2 4" },
  bolted: { stroke: "#f0883e", strokeWidth: 1.5 },
  slip_fit: { stroke: "#39c5cf", strokeWidth: 1, strokeDasharray: "6 3" },
  mate: { stroke: "#58a6ff", strokeWidth: 1.5 },
};

// Fit bindings get their own solid pink/magenta — distinct from every Connection.kind color above
// AND from the coupling's dashed green, since a fit edge is neither a load-derivation nor a mate
// (it's a derived-DIMENSION edge).
const _FIT_STYLE: React.CSSProperties = { stroke: "#f778ba", strokeWidth: 2 };

// Join annotations (2026-07-27, packages/ledger/schema.py::JoinAnnotation; wired into the graph
// 2026-08-01) attach BOM/documentation-grade "how actually joined" data (bolted/press_fit/welded/
// adhesive/custom) onto an EXISTING Connection. Distinct from every color above: the
// _CONNECTION_KIND_STYLE colors encode the GEOMETRIC join type (Connection.kind), the coupling color
// encodes a derived load, and _FIT_STYLE encodes a derived dimension -- this one encodes "a
// real-world fastening method has been recorded for this joint", which takes over the edge's color
// entirely once present (edgeStyleFor below checks it ahead of connectionKind) rather than blending
// with it, so it needs its own unused hue: solid red, distinct from the containment/bolted/slip_fit/
// mate quartet, the dashed green coupling, and the pink fit style.
const _JOIN_ANNOTATION_STYLE: React.CSSProperties = { stroke: "#f85149", strokeWidth: 2 };

export function edgeStyleFor(e: EKGComputedEdge): React.CSSProperties {
  if (e.kind === "coupling") return { stroke: "#3fb950", strokeWidth: 1.5, strokeDasharray: "6 3" };
  if (e.kind === "fit") return _FIT_STYLE;
  if (e.hasJoinAnnotation) return _JOIN_ANNOTATION_STYLE;
  return _CONNECTION_KIND_STYLE[e.connectionKind ?? "mate"] ?? _CONNECTION_KIND_STYLE.mate;
}

function EKGCardNode({ id, data }: NodeProps<EKGFlowNode>) {
  const { subsystemType, disconnected, selected, hasCoupling, params } = data;
  const visibleParams = params.slice(0, _MAX_VISIBLE_PARAMS);
  const hiddenCount = params.length - visibleParams.length;
  return (
    <div
      data-testid={`ekg-node-${id}`}
      data-selected={selected}
      data-disconnected={disconnected}
      data-has-coupling={hasCoupling}
      style={{
        background: "#161b22",
        border: disconnected ? "1.5px dashed #d29922" : "1px solid #30363d",
        borderRadius: 8,
        padding: "8px 12px",
        minWidth: 150,
        maxWidth: 220,
        boxShadow: selected ? "0 0 0 2px #58a6ff" : "none",
        cursor: "pointer",
      }}
    >
      <Handle type="target" position={Position.Top} style={handleStyle} />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
        <div style={{ fontWeight: 700, fontSize: 12, color: "#c9d1d9" }}>{id}</div>
        {hasCoupling && (
          <span
            title="A coupling (derived load) targets this part — see packages/couplings. Shown here even when it has no source-instance edge to draw (literal-value inputs)."
            style={{
              fontSize: 8, color: "#3fb950", border: "1px solid #3fb950", borderRadius: 4,
              padding: "1px 4px", lineHeight: 1.4, whiteSpace: "nowrap",
            }}
          >
            load
          </span>
        )}
      </div>
      <div style={{ fontSize: 10, color: "#8b949e", marginTop: 2 }}>{subsystemType}</div>
      {visibleParams.length > 0 && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid #21262d" }} data-testid={`ekg-node-${id}-params`}>
          {visibleParams.map((p) => (
            <div
              key={p.key}
              style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 9, color: "#8b949e", lineHeight: 1.5 }}
            >
              <span>{p.key}</span>
              <span style={{ color: "#c9d1d9" }}>
                {formatParamValue(p.value)}
                {p.unit ? ` ${p.unit}` : ""}
              </span>
            </div>
          ))}
          {hiddenCount > 0 && (
            <div style={{ fontSize: 9, color: "#6e7681", marginTop: 2 }}>+{hiddenCount} more</div>
          )}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={handleStyle} />
    </div>
  );
}

const handleStyle = { background: "#30363d", border: "1px solid #8b949e", width: 6, height: 6 };

const nodeTypes: NodeTypes = { ekgCard: EKGCardNode };

// --- top-level component ------------------------------------------------------------------------

export function EKGGraphView({ ledger, selectedInstanceId, onSelectInstance }: EKGGraphViewProps) {
  // Defense in depth beyond the `ledger === null` case: getLedger() checks res.ok (2026-07-19 review,
  // CRITICAL — an unchecked 401/503 error body used to reach here as a truthy-but-malformed object
  // and crash on Object.keys(undefined), with no ErrorBoundary anywhere to contain it), but a
  // component that's handed ledger data shouldn't ALSO assume every sub-field is always present.
  // Guarding directly on `ledger`/`ledger.instances` (rather than through an intermediate boolean)
  // also lets TS narrow `ledger` to non-null for the EKGGraphCanvas branch below.
  if (!ledger || !ledger.instances || Object.keys(ledger.instances).length === 0) {
    return (
      <div style={emptyState} data-testid="ekg-empty-state">
        No parts yet — ask the copilot to build something
      </div>
    );
  }

  // Constraint 10: no ReactFlow canvas mounted at all for the empty/malformed case (avoids any
  // ReactFlow-in-jsdom concerns for the trivial case) — `ledger` here is narrowed non-null/non-empty.
  return (
    <ReactFlowProvider>
      <EKGGraphCanvas ledger={ledger} selectedInstanceId={selectedInstanceId} onSelectInstance={onSelectInstance} />
    </ReactFlowProvider>
  );
}

interface EKGGraphCanvasProps {
  ledger: LedgerGraphData;
  selectedInstanceId?: string | null;
  onSelectInstance: (instanceId: string) => void;
}

function EKGGraphCanvas({ ledger, selectedInstanceId, onSelectInstance }: EKGGraphCanvasProps) {
  const computed = useMemo(() => computeGraphData(ledger), [ledger]);
  const [nodes, setNodes, onNodesChange] = useNodesState<EKGFlowNode>([]);
  const [edges, setEdges] = useEdgesState<Edge>([]);

  // Position-preservation (constraint 5) — its own effect, separate from edge recomputation, so a
  // pure edge-label change doesn't disturb node positions and vice versa.
  useEffect(() => {
    setNodes((prev) => mergeNodePositions(prev, computed.nodes, selectedInstanceId));
  }, [computed.nodes, selectedInstanceId, setNodes]);

  // Edges — constraint 7: Connections are symmetric, no arrowhead, styled per `connectionKind` (see
  // edgeStyleFor) — or, when a JoinAnnotation is attached, per that instead (2026-08-01). Couplings
  // render dashed green WITH a directional arrowhead pointing at the
  // target (value flows FROM source INTO target) — this directional distinction is the whole point
  // of "how they interact". Fit bindings (2026-07-27) are directional the same way (host -> connector).
  useEffect(() => {
    setEdges(
      computed.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        labelStyle: { fill: "#8b949e", fontSize: 9 },
        labelBgStyle: { fill: "#0d1117", fillOpacity: 0.8 },
        style: edgeStyleFor(e),
        markerEnd: e.kind === "coupling" ? { type: MarkerType.ArrowClosed, color: "#3fb950" }
          : e.kind === "fit" ? { type: MarkerType.ArrowClosed, color: "#f778ba" }
          : undefined,
      })),
    );
  }, [computed.edges, setEdges]);

  const handleNodeClick: NodeMouseHandler<EKGFlowNode> = useCallback(
    (_event, node) => onSelectInstance(node.id),
    [onSelectInstance],
  );

  return (
    <div style={{ position: "absolute", inset: 0 }} data-testid="ekg-graph-view">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        colorMode="dark"
        fitView
      >
        <Background variant={BackgroundVariant.Dots} color="#30363d" bgColor="#0d1117" gap={16} size={1} />
        <Controls style={{ background: "#161b22", border: "1px solid #30363d", borderRadius: 8 }} />
        <MiniMap
          style={{ background: "#161b22", border: "1px solid #30363d", borderRadius: 8 }}
          maskColor="rgba(13, 17, 23, 0.65)"
          bgColor="#161b22"
          nodeColor={(n) => (((n as EKGFlowNode).data?.disconnected) ? "#d29922" : "#58a6ff")}
        />
      </ReactFlow>
    </div>
  );
}

const emptyState: React.CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center", minHeight: 200,
  padding: "12px 14px", border: "1px solid #30363d", borderRadius: 10, background: "#161b22",
  color: "#8b949e", fontSize: 12, textAlign: "center",
};
