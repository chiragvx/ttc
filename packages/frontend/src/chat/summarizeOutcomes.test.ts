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
