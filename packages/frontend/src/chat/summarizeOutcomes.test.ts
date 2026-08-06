import { describe, expect, it } from "vitest";
import { summarizeOutcomes } from "./summarizeOutcomes";
import type { ChatMessage } from "../types";

const base: ChatMessage = { id: "m1", role: "assistant", text: "" };

describe("summarizeOutcomes — connection ops (Phase 1b)", () => {
  it("feeds a REJECTED mate (with reason) back to the model so it doesn't re-propose the same wrong one", () => {
    const m: ChatMessage = {
      ...base,
      connectionOps: [{ op: "add_connection", a_instance: "w1", a_interface: "wing_mount", b_instance: "b1", b_interface: "tip_right" }],
      connectionOpOutcomes: [{ op: {} as any, status: "REJECTED", connectionId: null, message: "wing_panel has no interface 'wing_mount' (declares: ['root'])" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("REJECTED");
    expect(s).toContain("no interface 'wing_mount'");
  });

  it("feeds an APPLIED mate's minted connection_id back so a later remove can target it", () => {
    const m: ChatMessage = {
      ...base,
      connectionOps: [{ op: "add_connection", a_instance: "w1", a_interface: "root", b_instance: "b1", b_interface: "tip_right" }],
      connectionOpOutcomes: [{ op: {} as any, status: "APPLIED", connectionId: "conn_1" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("connection_id=conn_1");
    expect(s).toContain("w1.root <-> b1.tip_right");
  });

  it("returns null when there are no outcomes of any kind", () => {
    expect(summarizeOutcomes(base)).toBeNull();
  });
});

describe("summarizeOutcomes — coupling ops (Phase 2b)", () => {
  it("feeds a REJECTED coupling (with reason) back to the model so it doesn't re-propose the same wrong one", () => {
    const m: ChatMessage = {
      ...base,
      couplingOps: [{ op: "add_coupling", target_instance: "bracket_1", relation: "load_from_motor_thrust", inputs: [{ name: "motor", from_instance: "motor_1", from_param: "thrust_n" }] }],
      couplingOpOutcomes: [{ op: {} as any, status: "REJECTED", couplingId: null, message: "motor_1 has no param 'thrust_n' (declares: ['rpm', 'mass_g'])" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("REJECTED");
    expect(s).toContain("no param 'thrust_n'");
  });

  it("feeds an APPLIED coupling's minted coupling_id back so a later remove can target it", () => {
    const m: ChatMessage = {
      ...base,
      couplingOps: [{ op: "add_coupling", target_instance: "bracket_1", relation: "load_from_motor_thrust", inputs: [{ name: "motor", from_instance: "motor_1", from_param: "thrust_n" }] }],
      couplingOpOutcomes: [{ op: {} as any, status: "APPLIED", couplingId: "coupling_1" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("coupling_id=coupling_1");
    expect(s).toContain("couple bracket_1 <- load_from_motor_thrust");
  });

  it("returns null when there are no coupling outcomes either", () => {
    expect(summarizeOutcomes({ ...base, couplingOps: [] })).toBeNull();
  });
});

describe("summarizeOutcomes — fit ops (2026-07-27)", () => {
  it("feeds a REJECTED fit (with reason) back to the model so it doesn't re-propose the same wrong one", () => {
    const m: ChatMessage = {
      ...base,
      fitOps: [{ op: "fit_connector", connector_instance: "sleeve1", host_instance: "post1" }],
      fitOpOutcomes: [{ op: {} as any, status: "REJECTED", fitId: null, message: "post1's cross-section is 30x20mm, not square" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("REJECTED");
    expect(s).toContain("not square");
  });

  it("feeds an APPLIED fit's minted fit_id back so a later resync/unfit can target it", () => {
    const m: ChatMessage = {
      ...base,
      fitOps: [{ op: "fit_connector", connector_instance: "sleeve1", host_instance: "post1" }],
      fitOpOutcomes: [{ op: {} as any, status: "APPLIED", fitId: "fit_1" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("fit_id=fit_1");
    expect(s).toContain("fit sleeve1 <- post1");
  });

  it("summarizes resync_fit and unfit_connector distinctly from fit_connector", () => {
    const m: ChatMessage = {
      ...base,
      fitOps: [{ op: "resync_fit", id: "fit_1" }, { op: "unfit_connector", id: "fit_1" }],
      fitOpOutcomes: [{ op: {} as any, status: "APPLIED", fitId: "fit_1" }, { op: {} as any, status: "APPLIED", fitId: "fit_1" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("resync_fit fit_1");
    expect(s).toContain("unfit_connector fit_1");
  });

  it("returns null when there are no fit outcomes either", () => {
    expect(summarizeOutcomes({ ...base, fitOps: [] })).toBeNull();
  });
});

describe("summarizeOutcomes — region ops (2026-08-04)", () => {
  it("feeds a REJECTED region (with reason) back to the model so it doesn't re-propose the same wrong one", () => {
    const m: ChatMessage = {
      ...base,
      regionOps: [{ op: "add_region", host_instance: "gearbox_1", kind: "keep_out", label: "gear_train_clearance", x_mm: 0, y_mm: 0, z_mm: 0, dx_mm: 20, dy_mm: 20, dz_mm: 10 }],
      regionOpOutcomes: [{ op: {} as any, status: "REJECTED", regionId: null, message: "unknown instance 'gearbox_1'" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("REJECTED");
    expect(s).toContain("unknown instance 'gearbox_1'");
  });

  it("feeds an APPLIED region's minted region_id back so a later remove can target it", () => {
    const m: ChatMessage = {
      ...base,
      regionOps: [{ op: "add_region", host_instance: "gearbox_1", kind: "keep_out", label: "gear_train_clearance", x_mm: 0, y_mm: 0, z_mm: 0, dx_mm: 20, dy_mm: 20, dz_mm: 10 }],
      regionOpOutcomes: [{ op: {} as any, status: "APPLIED", regionId: "region_1" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("region_id=region_1");
    expect(s).toContain("region gearbox_1: gear_train_clearance (keep_out)");
  });

  it("summarizes remove_region distinctly from add_region", () => {
    const m: ChatMessage = {
      ...base,
      regionOps: [{ op: "remove_region", id: "region_1" }],
      regionOpOutcomes: [{ op: {} as any, status: "APPLIED", regionId: "region_1" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("remove_region region_1");
  });

  it("returns null when there are no region outcomes either", () => {
    expect(summarizeOutcomes({ ...base, regionOps: [] })).toBeNull();
  });
});

describe("summarizeOutcomes — cascade cleanup nudge (2026-08-05)", () => {
  it("surfaces a remove_instance's cascade-removed coupling/region ids so the model knows to reconsider re-adding them", () => {
    const m: ChatMessage = {
      ...base,
      instanceOps: [{ op: "remove_instance", instance_id: "stage1_gear" }],
      instanceOpOutcomes: [{
        op: {} as any, status: "APPLIED", instanceId: "stage1_gear", subsystemType: "spur_gear",
        removedCouplingIds: ["coupling_1", "coupling_2"], removedRegionIds: ["region_1"],
      }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("coupling coupling_1");
    expect(s).toContain("coupling coupling_2");
    expect(s).toContain("region region_1");
    expect(s).toContain("cascade also removed");
    expect(s).toContain("re-add these if they're still needed");
  });

  it("surfaces a remove_instance's cascade-removed connection/fit_binding/join_annotation ids too", () => {
    const m: ChatMessage = {
      ...base,
      instanceOps: [{ op: "remove_instance", instance_id: "post1" }],
      instanceOpOutcomes: [{
        op: {} as any, status: "APPLIED", instanceId: "post1", subsystemType: "standoff",
        removedConnectionIds: ["conn_1"], removedFitBindingIds: ["fit_1"], removedJoinAnnotationIds: ["join_1"],
      }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("connection conn_1");
    expect(s).toContain("fit_binding fit_1");
    expect(s).toContain("join_annotation join_1");
  });

  it("leaves a remove_instance with no cascade removals producing the existing plain summary, unchanged", () => {
    const m: ChatMessage = {
      ...base,
      instanceOps: [{ op: "remove_instance", instance_id: "stage1_gear" }],
      instanceOpOutcomes: [{ op: {} as any, status: "APPLIED", instanceId: "stage1_gear", subsystemType: "spur_gear" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toBe("[outcomes: remove_instance -> APPLIED (instance_id=stage1_gear)]");
    expect(s).not.toContain("cascade");
  });

  it("leaves a remove_instance with ALL removed_*_ids explicitly empty producing the existing plain summary, unchanged", () => {
    const m: ChatMessage = {
      ...base,
      instanceOps: [{ op: "remove_instance", instance_id: "stage1_gear" }],
      instanceOpOutcomes: [{
        op: {} as any, status: "APPLIED", instanceId: "stage1_gear", subsystemType: "spur_gear",
        removedConnectionIds: [], removedCouplingIds: [], removedRegionIds: [], removedFitBindingIds: [], removedJoinAnnotationIds: [],
      }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toBe("[outcomes: remove_instance -> APPLIED (instance_id=stage1_gear)]");
    expect(s).not.toContain("cascade");
  });

  it("surfaces a remove_connection's cascade-removed join_annotation ids", () => {
    const m: ChatMessage = {
      ...base,
      connectionOps: [{ op: "remove_connection", id: "conn_1" }],
      connectionOpOutcomes: [{ op: {} as any, status: "APPLIED", connectionId: "conn_1", removedJoinAnnotationIds: ["join_1", "join_2"] }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toContain("join_annotation join_1");
    expect(s).toContain("join_annotation join_2");
    expect(s).toContain("cascade also removed");
  });

  it("leaves a remove_connection with no cascade removals producing the existing plain summary, unchanged", () => {
    const m: ChatMessage = {
      ...base,
      connectionOps: [{ op: "remove_connection", id: "conn_1" }],
      connectionOpOutcomes: [{ op: {} as any, status: "APPLIED", connectionId: "conn_1" }],
    };
    const s = summarizeOutcomes(m)!;
    expect(s).toBe("[outcomes: remove_connection conn_1 -> APPLIED (connection_id=conn_1)]");
    expect(s).not.toContain("cascade");
  });
});
