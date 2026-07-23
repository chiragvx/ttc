import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  EKGGraphView,
  computeGraphData,
  edgeStyleFor,
  mergeNodePositions,
  type EKGComputedEdge,
  type EKGComputedNode,
  type EKGFlowNode,
} from "./EKGGraphView";
import type { LedgerGraphData } from "./types";

function makeLedger(overrides: Partial<LedgerGraphData> = {}): LedgerGraphData {
  return {
    instances: {},
    connections: [],
    couplings: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------------------------
// computeGraphData — pure function, no rendering at all (constraint 4). This is where every
// dangling-reference-skip / touched-vs-disconnected rule from constraints 2-3 is actually tested;
// the component-level tests below only need to check that the RESULT reaches the DOM correctly.
// ---------------------------------------------------------------------------------------------
describe("computeGraphData", () => {
  it("returns empty nodes/edges for an empty ledger", () => {
    expect(computeGraphData(makeLedger())).toEqual({ nodes: [], edges: [] });
  });

  it("skips a connection with a dangling endpoint instead of crashing", () => {
    const ledger = makeLedger({
      instances: { i1: { id: "i1", subsystem_type: "bracket" } },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "ghost", interface: "bottom" }, kind: "mate", gap_mm: 0 },
      ],
    });
    const { nodes, edges } = computeGraphData(ledger);
    expect(edges).toEqual([]);
    expect(nodes).toEqual([{ id: "i1", subsystemType: "bracket", disconnected: true, params: [] }]);
  });

  it("skips a coupling input with a dangling from_instance instead of crashing", () => {
    const ledger = makeLedger({
      instances: { i1: { id: "i1", subsystem_type: "bracket" } },
      couplings: [
        { id: "k1", target_instance: "i1", relation: "bolt_preload", inputs: { load: { from_instance: "ghost", from_param: "mass_g" } } },
      ],
    });
    const { nodes, edges } = computeGraphData(ledger);
    expect(edges).toEqual([]);
    // the target itself still resolves, so it's touched even though its only input's source is dangling
    expect(nodes).toEqual([{ id: "i1", subsystemType: "bracket", disconnected: false, params: [] }]);
  });

  it("does not crash and skips both a dangling connection AND a dangling coupling target on the same ledger", () => {
    const ledger = makeLedger({
      instances: { i1: { id: "i1", subsystem_type: "bracket" } },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "ghost", interface: "bottom" }, kind: "mate", gap_mm: 0 },
      ],
      couplings: [
        { id: "k1", target_instance: "also-ghost", relation: "bolt_preload", inputs: { load: { from_instance: "i1", from_param: "mass_g" } } },
      ],
    });
    expect(() => computeGraphData(ledger)).not.toThrow();
    const { edges } = computeGraphData(ledger);
    expect(edges).toEqual([]);
  });

  // 2026-07-19 review (HIGH), carried forward: a coupling target used to only get marked "touched"
  // from INSIDE the per-input loop, gated on that input having a from_instance — so a coupling with
  // only literal-value inputs (a real, valid CouplingInput form) never marked its own resolvable
  // target as connected.
  it("does not falsely flag a coupling target as disconnected when all its inputs are literal values", () => {
    const ledger = makeLedger({
      instances: { duct: { id: "duct", subsystem_type: "round_tube" } },
      couplings: [
        { id: "k1", target_instance: "duct", relation: "diameter_check", inputs: { diameter: { value: 50.0 } } },
      ],
    });
    const { nodes } = computeGraphData(ledger);
    expect(nodes).toEqual([{ id: "duct", subsystemType: "round_tube", disconnected: false, params: [] }]);
  });

  // 2026-07-19 review (MEDIUM), carried forward: when a coupling's target was dangling, the whole
  // coupling (including every input) used to be skipped via `continue` BEFORE the input loop ran —
  // so a perfectly valid from_instance source on that same coupling never got marked "touched"
  // either, falsely flagging an unrelated, legitimately-wired node as disconnected just because of a
  // DIFFERENT node's bad reference.
  it("does not falsely flag a coupling's source instance as disconnected when only the target is dangling", () => {
    const ledger = makeLedger({
      instances: { plenum: { id: "plenum", subsystem_type: "lofted_spindle" } },
      couplings: [
        { id: "k1", target_instance: "ghost-motor", relation: "flow_rate", inputs: { flow: { from_instance: "plenum", from_param: "volume_mm3" } } },
      ],
    });
    const { nodes } = computeGraphData(ledger);
    expect(nodes).toEqual([{ id: "plenum", subsystemType: "lofted_spindle", disconnected: false, params: [] }]);
  });

  it("flags a node touched by neither a connection nor a coupling as disconnected", () => {
    const ledger = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
        i2: { id: "i2", subsystem_type: "enclosure" },
        lonely: { id: "lonely", subsystem_type: "spacer" },
      },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "i2", interface: "bottom" }, kind: "mate", gap_mm: 0 },
      ],
    });
    const { nodes } = computeGraphData(ledger);
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    expect(byId.lonely.disconnected).toBe(true);
    expect(byId.i1.disconnected).toBe(false);
    expect(byId.i2.disconnected).toBe(false);
  });

  it("produces one connection edge (no arrowhead-relevant fields, symmetric) and one coupling edge (directional: source -> target)", () => {
    const ledger = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
        i2: { id: "i2", subsystem_type: "enclosure" },
        i3: { id: "i3", subsystem_type: "fastener" },
      },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "i2", interface: "bottom" }, kind: "mate", gap_mm: 0 },
      ],
      couplings: [
        { id: "k1", target_instance: "i3", relation: "bolt_preload", inputs: { load: { from_instance: "i1", from_param: "mass_g" } } },
      ],
    });
    const { edges } = computeGraphData(ledger);
    expect(edges).toEqual([
      { id: "conn-c1", source: "i1", target: "i2", label: "mate: top<->bottom", kind: "connection", connectionKind: "mate" },
      { id: "cpl-k1-0", source: "i1", target: "i3", label: "bolt_preload", kind: "coupling" },
    ]);
  });

  it("degrades gracefully (no throw, empty result) when instances/connections/couplings are missing entirely", () => {
    const malformed = {} as unknown as LedgerGraphData;
    expect(() => computeGraphData(malformed)).not.toThrow();
    expect(computeGraphData(malformed)).toEqual({ nodes: [], edges: [] });
  });

  it("extracts a node's params, sorted by key, for display on its card", () => {
    const ledger = makeLedger({
      instances: {
        i1: {
          id: "i1",
          subsystem_type: "solar_panel_backing_plate",
          params: {
            width_mm: { value: 85, unit: "mm" },
            thickness_mm: { value: 1.5, unit: "mm" },
            n_holes: { value: 4, unit: "count" },
          },
        },
      },
    });
    const { nodes } = computeGraphData(ledger);
    expect(nodes).toEqual([
      {
        id: "i1",
        subsystemType: "solar_panel_backing_plate",
        disconnected: true,
        params: [
          { key: "n_holes", value: 4, unit: "count" },
          { key: "thickness_mm", value: 1.5, unit: "mm" },
          { key: "width_mm", value: 85, unit: "mm" },
        ],
      },
    ]);
  });

  it("defaults to an empty params list when an instance declares no params field", () => {
    const ledger = makeLedger({ instances: { i1: { id: "i1", subsystem_type: "bracket" } } });
    const { nodes } = computeGraphData(ledger);
    expect(nodes[0].params).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------
// edgeStyleFor — pure per-Connection.kind styling (2026-07-22). Previously `kind` was only ever
// text in the edge label, cosmetically identical for every value -- this is what actually makes
// the relationship type visible in the graph, not just named.
// ---------------------------------------------------------------------------------------------
describe("computeGraphData connectionKind threading", () => {
  it("carries Connection.kind through onto the computed edge", () => {
    const ledger = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
        i2: { id: "i2", subsystem_type: "bracket" },
      },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "i2", interface: "bottom" }, kind: "containment", gap_mm: 0 },
      ],
    });
    const { edges } = computeGraphData(ledger);
    expect(edges[0].connectionKind).toBe("containment");
  });
});

describe("edgeStyleFor", () => {
  const edge = (over: Partial<EKGComputedEdge>): EKGComputedEdge => ({
    id: "e", source: "a", target: "b", label: "", kind: "connection", ...over,
  });

  it("styles a coupling edge dashed green, ignoring connectionKind", () => {
    expect(edgeStyleFor(edge({ kind: "coupling" })).stroke).toBe("#3fb950");
  });

  it("styles containment, bolted, slip_fit, and mate connections DIFFERENTLY from each other", () => {
    const kinds = ["containment", "bolted", "slip_fit", "mate"];
    const styles = kinds.map((k) => edgeStyleFor(edge({ connectionKind: k })));
    const strokes = styles.map((s) => `${s.stroke}|${s.strokeDasharray ?? ""}`);
    expect(new Set(strokes).size).toBe(kinds.length); // all four visually distinct
  });

  it("falls back to the mate style for an unset or unrecognized connectionKind", () => {
    const mate = edgeStyleFor(edge({ connectionKind: "mate" }));
    expect(edgeStyleFor(edge({}))).toEqual(mate);
    expect(edgeStyleFor(edge({ connectionKind: "some_future_kind" }))).toEqual(mate);
  });
});

// ---------------------------------------------------------------------------------------------
// mergeNodePositions — the position-preservation merge (constraint 5), tested by mocking the
// position-bearing internal state directly rather than asserting on real pixel coordinates through
// jsdom (which has no real layout engine).
// ---------------------------------------------------------------------------------------------
describe("mergeNodePositions", () => {
  function flowNode(id: string, x: number, y: number, disconnected = false): EKGFlowNode {
    return {
      id,
      type: "ekgCard",
      position: { x, y },
      data: { subsystemType: "bracket", disconnected, selected: false, params: [] },
    };
  }

  it("keeps the EXISTING (possibly dragged) position for an id already present in prevNodes", () => {
    const prev = [flowNode("i1", 999, -42)];
    const computed: EKGComputedNode[] = [{ id: "i1", subsystemType: "bracket", disconnected: false, params: [] }];

    const merged = mergeNodePositions(prev, computed, null);

    expect(merged).toHaveLength(1);
    expect(merged[0].position).toEqual({ x: 999, y: -42 });
  });

  it("assigns a fresh deterministic position to a genuinely new id", () => {
    const computed: EKGComputedNode[] = [{ id: "brand-new", subsystemType: "spacer", disconnected: true, params: [] }];

    const merged = mergeNodePositions([], computed, null);

    expect(merged).toHaveLength(1);
    expect(merged[0].id).toBe("brand-new");
    expect(Number.isFinite(merged[0].position.x)).toBe(true);
    expect(Number.isFinite(merged[0].position.y)).toBe(true);
  });

  it("drops an id no longer present in the freshly computed nodes", () => {
    const prev = [flowNode("stays", 1, 1), flowNode("gone", 2, 2)];
    const computed: EKGComputedNode[] = [{ id: "stays", subsystemType: "bracket", disconnected: false, params: [] }];

    const merged = mergeNodePositions(prev, computed, null);

    expect(merged.map((n) => n.id)).toEqual(["stays"]);
  });

  it("refreshes data (disconnected/selected) on an existing node without touching its position", () => {
    const prev = [flowNode("i1", 5, 7, false)];
    const computed: EKGComputedNode[] = [{ id: "i1", subsystemType: "bracket", disconnected: true, params: [] }];

    const merged = mergeNodePositions(prev, computed, "i1");

    expect(merged[0].position).toEqual({ x: 5, y: 7 });
    expect(merged[0].data.disconnected).toBe(true);
    expect(merged[0].data.selected).toBe(true);
  });

  it("does not mark any node selected when selectedInstanceId is null/undefined", () => {
    const computed: EKGComputedNode[] = [{ id: "i1", subsystemType: "bracket", disconnected: false, params: [] }];
    expect(mergeNodePositions([], computed, null)[0].data.selected).toBe(false);
    expect(mergeNodePositions([], computed, undefined)[0].data.selected).toBe(false);
  });

  // 2026-07-19 review (LOW): a bare {id, type, position, data} literal for an EXISTING node dropped
  // every xyflow-owned field (measured, dragging, z, ...) the library itself writes onto these
  // controlled node objects, forcing an unnecessary re-measure pass (visible flicker) on every merge
  // — including a plain node-selection click, since selectedInstanceId is a merge-effect dependency.
  it("preserves xyflow-owned fields (e.g. measured, dragging) on an existing node across a merge", () => {
    const prev: EKGFlowNode = {
      ...flowNode("i1", 5, 7),
      measured: { width: 140, height: 60 },
      dragging: true,
    } as EKGFlowNode;
    const computed: EKGComputedNode[] = [{ id: "i1", subsystemType: "bracket", disconnected: false, params: [] }];

    const merged = mergeNodePositions([prev], computed, null);

    expect((merged[0] as typeof prev).measured).toEqual({ width: 140, height: 60 });
    expect((merged[0] as typeof prev).dragging).toBe(true);
  });
});

// ---------------------------------------------------------------------------------------------
// Component-level — mounts the real @xyflow/react canvas for the populated case.
// ---------------------------------------------------------------------------------------------
describe("EKGGraphView", () => {
  it("shows an empty-state message when the ledger is null, not a crash", () => {
    render(<EKGGraphView ledger={null} onSelectInstance={vi.fn()} />);
    expect(screen.getByText(/no parts yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("ekg-graph-view")).not.toBeInTheDocument();
  });

  it("shows the same empty-state message when the ledger has zero instances", () => {
    render(<EKGGraphView ledger={makeLedger()} onSelectInstance={vi.fn()} />);
    expect(screen.getByText(/no parts yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("ekg-graph-view")).not.toBeInTheDocument();
  });

  // 2026-07-19 review (CRITICAL), carried forward: a truthy-but-malformed ledger (e.g. an unchecked
  // auth-error JSON body reaching this component, the exact bug getLedger()'s missing res.ok check
  // produced) must not crash Object.keys(ledger.instances) — and must not mount the ReactFlow canvas.
  it("shows the empty state instead of crashing when ledger is truthy but missing expected fields", () => {
    const malformed = { detail: "unauthorized — set Authorization: Bearer <AUTH_TOKEN>" } as unknown as LedgerGraphData;
    expect(() => render(<EKGGraphView ledger={malformed} onSelectInstance={vi.fn()} />)).not.toThrow();
    expect(screen.getByText(/no parts yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("ekg-graph-view")).not.toBeInTheDocument();
  });

  it("renders one node per instance for a populated ledger", () => {
    const ledger = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
        i2: { id: "i2", subsystem_type: "enclosure" },
        i3: { id: "i3", subsystem_type: "fastener" },
      },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "i2", interface: "bottom" }, kind: "mate", gap_mm: 0 },
      ],
      couplings: [
        { id: "k1", target_instance: "i3", relation: "bolt_preload", inputs: { load: { from_instance: "i1", from_param: "mass_g" } } },
      ],
    });
    render(<EKGGraphView ledger={ledger} onSelectInstance={vi.fn()} />);

    expect(screen.getByTestId("ekg-graph-view")).toBeInTheDocument();
    expect(screen.getByTestId("ekg-node-i1")).toBeInTheDocument();
    expect(screen.getByTestId("ekg-node-i2")).toBeInTheDocument();
    expect(screen.getByTestId("ekg-node-i3")).toBeInTheDocument();
    expect(screen.getByText("i1")).toBeInTheDocument();
    expect(screen.getByText("bracket")).toBeInTheDocument();
  });

  it("does not crash when a connection or coupling references a nonexistent instance", () => {
    const ledger = makeLedger({
      instances: { i1: { id: "i1", subsystem_type: "bracket" } },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "ghost", interface: "bottom" }, kind: "mate", gap_mm: 0 },
      ],
      couplings: [
        { id: "k1", target_instance: "also-ghost", relation: "bolt_preload", inputs: { load: { from_instance: "i1", from_param: "mass_g" } } },
      ],
    });
    expect(() => render(<EKGGraphView ledger={ledger} onSelectInstance={vi.fn()} />)).not.toThrow();
    expect(screen.getByTestId("ekg-node-i1")).toBeInTheDocument();
  });

  it("calls onSelectInstance with the right id when a node is clicked", () => {
    const onSelectInstance = vi.fn();
    const ledger = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
        i2: { id: "i2", subsystem_type: "enclosure" },
      },
    });
    render(<EKGGraphView ledger={ledger} onSelectInstance={onSelectInstance} />);

    fireEvent.click(screen.getByTestId("ekg-node-i2"));
    expect(onSelectInstance).toHaveBeenCalledWith("i2");
  });

  it("gives a disconnected node a different rendered attribute than a connected node", () => {
    const ledger = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
        i2: { id: "i2", subsystem_type: "enclosure" },
        lonely: { id: "lonely", subsystem_type: "spacer" },
      },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "i2", interface: "bottom" }, kind: "mate", gap_mm: 0 },
      ],
    });
    render(<EKGGraphView ledger={ledger} onSelectInstance={vi.fn()} />);

    expect(screen.getByTestId("ekg-node-lonely")).toHaveAttribute("data-disconnected", "true");
    expect(screen.getByTestId("ekg-node-i1")).toHaveAttribute("data-disconnected", "false");
    expect(screen.getByTestId("ekg-node-i2")).toHaveAttribute("data-disconnected", "false");
  });

  it("marks the selected node distinctly, independent of its disconnected state", () => {
    const ledger = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
        lonely: { id: "lonely", subsystem_type: "spacer" },
      },
    });
    render(<EKGGraphView ledger={ledger} selectedInstanceId="lonely" onSelectInstance={vi.fn()} />);

    const node = screen.getByTestId("ekg-node-lonely");
    expect(node).toHaveAttribute("data-selected", "true");
    expect(node).toHaveAttribute("data-disconnected", "true"); // selected AND disconnected simultaneously
    expect(screen.getByTestId("ekg-node-i1")).toHaveAttribute("data-selected", "false");
  });

  // Position-preservation's observable contract (constraint 5): a ledger update that adds a new
  // instance to an already-rendered graph must not remove/reset the pre-existing nodes. Exact pixel
  // coordinates aren't assertable through jsdom (no real layout engine) — mergeNodePositions above
  // covers that directly — but "did the old node survive the update" is directly observable here.
  it("keeps pre-existing nodes mounted when a ledger update adds a new instance", () => {
    const onSelectInstance = vi.fn();
    const ledger1 = makeLedger({
      instances: { i1: { id: "i1", subsystem_type: "bracket" } },
    });
    const { rerender } = render(<EKGGraphView ledger={ledger1} onSelectInstance={onSelectInstance} />);
    expect(screen.getByTestId("ekg-node-i1")).toBeInTheDocument();

    const ledger2 = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
        i2: { id: "i2", subsystem_type: "enclosure" },
      },
    });
    rerender(<EKGGraphView ledger={ledger2} onSelectInstance={onSelectInstance} />);

    expect(screen.getByTestId("ekg-node-i1")).toBeInTheDocument();
    expect(screen.getByTestId("ekg-node-i2")).toBeInTheDocument();
  });
});
