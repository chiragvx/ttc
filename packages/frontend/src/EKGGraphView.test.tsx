import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EKGGraphView } from "./EKGGraphView";
import type { LedgerGraphData } from "./types";

function makeLedger(overrides: Partial<LedgerGraphData> = {}): LedgerGraphData {
  return {
    instances: {},
    connections: [],
    couplings: [],
    ...overrides,
  };
}

describe("EKGGraphView", () => {
  it("shows an empty-state message when the ledger is null, not a crash", () => {
    render(<EKGGraphView ledger={null} onSelectInstance={vi.fn()} />);
    expect(screen.getByText(/no parts yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("ekg-graph-svg")).not.toBeInTheDocument();
  });

  it("shows the same empty-state message when the ledger has zero instances", () => {
    render(<EKGGraphView ledger={makeLedger()} onSelectInstance={vi.fn()} />);
    expect(screen.getByText(/no parts yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("ekg-graph-svg")).not.toBeInTheDocument();
  });

  it("renders one node per instance, plus connection and coupling edges", () => {
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

    expect(screen.getByTestId("ekg-graph-svg")).toBeInTheDocument();
    expect(screen.getByTestId("ekg-node-i1")).toBeInTheDocument();
    expect(screen.getByTestId("ekg-node-i2")).toBeInTheDocument();
    expect(screen.getByTestId("ekg-node-i3")).toBeInTheDocument();
    expect(screen.getByText("i1")).toBeInTheDocument();
    expect(screen.getByText("bracket")).toBeInTheDocument();
    expect(screen.getByText("mate: top<->bottom")).toBeInTheDocument();
    expect(screen.getByText("bolt_preload")).toBeInTheDocument();
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
    expect(onSelectInstance).toHaveBeenCalledOnce();
  });

  // The single most important test: this feature exists specifically to stop a dangling
  // connection/coupling reference (an endpoint instance_id that doesn't cleanly resolve — a real,
  // expected case per packages/subsystems/placement.py::connection_issues()) from crashing the
  // render. It must render everything that DOES resolve and silently skip what doesn't.
  it("does not crash when a connection or coupling references a nonexistent instance", () => {
    const ledger = makeLedger({
      instances: {
        i1: { id: "i1", subsystem_type: "bracket" },
      },
      connections: [
        { id: "c1", a: { instance_id: "i1", interface: "top" }, b: { instance_id: "ghost", interface: "bottom" }, kind: "mate", gap_mm: 0 },
      ],
      couplings: [
        { id: "k1", target_instance: "also-ghost", relation: "bolt_preload", inputs: { load: { from_instance: "i1", from_param: "mass_g" } } },
        { id: "k2", target_instance: "i1", relation: "bolt_preload", inputs: { load: { from_instance: "another-ghost", from_param: "mass_g" } } },
      ],
    });

    expect(() => render(<EKGGraphView ledger={ledger} onSelectInstance={vi.fn()} />)).not.toThrow();
    // the one real instance still renders...
    expect(screen.getByTestId("ekg-node-i1")).toBeInTheDocument();
    // ...but no dangling edge got drawn for any of the bogus references
    expect(screen.queryByTestId(/ekg-edge-/)).not.toBeInTheDocument();
  });

  it("gives a node with zero edges a different rendered attribute than a connected node", () => {
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

  // 2026-07-19 review (HIGH): a coupling target used to only get marked "touched" from INSIDE the
  // per-input loop, gated on that input having a from_instance — so a coupling with only literal-value
  // inputs (a real, valid CouplingInput form) never marked its own resolvable target as connected.
  it("does not falsely flag a coupling target as disconnected when all its inputs are literal values", () => {
    const ledger = makeLedger({
      instances: { duct: { id: "duct", subsystem_type: "round_tube" } },
      couplings: [
        { id: "k1", target_instance: "duct", relation: "diameter_check", inputs: { diameter: { value: 50.0 } } },
      ],
    });
    render(<EKGGraphView ledger={ledger} onSelectInstance={vi.fn()} />);
    expect(screen.getByTestId("ekg-node-duct")).toHaveAttribute("data-disconnected", "false");
  });

  // 2026-07-19 review (MEDIUM): when a coupling's target was dangling, the whole coupling (including
  // every input) used to be skipped via `continue` BEFORE the input loop ran — so a perfectly valid
  // from_instance source on that same coupling never got marked "touched" either, falsely flagging an
  // unrelated, legitimately-wired node as disconnected just because of a DIFFERENT node's bad reference.
  it("does not falsely flag a coupling's source instance as disconnected when only the target is dangling", () => {
    const ledger = makeLedger({
      instances: { plenum: { id: "plenum", subsystem_type: "lofted_spindle" } },
      couplings: [
        { id: "k1", target_instance: "ghost-motor", relation: "flow_rate", inputs: { flow: { from_instance: "plenum", from_param: "volume_mm3" } } },
      ],
    });
    render(<EKGGraphView ledger={ledger} onSelectInstance={vi.fn()} />);
    expect(screen.getByTestId("ekg-node-plenum")).toHaveAttribute("data-disconnected", "false");
  });

  // 2026-07-19 review (CRITICAL): defense in depth beyond the null check — a truthy-but-malformed
  // ledger (e.g. an unchecked auth-error JSON body reaching this component, the exact bug getLedger()'s
  // missing res.ok check produced) must not crash Object.keys(ledger.instances).
  it("shows the empty state instead of crashing when ledger is truthy but missing expected fields", () => {
    const malformed = { detail: "unauthorized — set Authorization: Bearer <AUTH_TOKEN>" } as unknown as LedgerGraphData;
    expect(() => render(<EKGGraphView ledger={malformed} onSelectInstance={vi.fn()} />)).not.toThrow();
    expect(screen.getByText(/no parts yet/i)).toBeInTheDocument();
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
});
