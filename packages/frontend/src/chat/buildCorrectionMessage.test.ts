import { describe, expect, it } from "vitest";
import { buildCorrectionMessage } from "./buildCorrectionMessage";
import type { InstanceOp, ValidationIssue, ValidationResult } from "../types";

function report(overrides: Partial<ValidationResult> & { geometricIssues?: ValidationIssue[] } = {}): ValidationResult {
  const { geometricIssues, ...rest } = overrides;
  return {
    ok: false,
    geometric: { ok: false, issues: geometricIssues ?? [], summary: "" },
    structural: { ok: true, issues: [], summary: "" },
    visual: null,
    vision_enabled: false,
    vision_ran: false,
    ...rest,
  };
}

function issue(check: string, message: string): ValidationIssue {
  return { check, severity: "warning", message, instances: ["x"] };
}

describe("buildCorrectionMessage", () => {
  it("builds the base message with round/max and every issue listed, with no prior-attempt note", () => {
    const r = report({ geometricIssues: [issue("connectivity", "rail_1 is disconnected")] });
    const msg = buildCorrectionMessage(r, 1, 2, []);
    expect(msg).toContain("Self-check of what you just built found problems:");
    expect(msg).toContain("- rail_1 is disconnected");
    expect(msg).toContain("(auto-correction round 1 of 2)");
    expect(msg).not.toContain("already tried");
    expect(msg).not.toContain("VISUAL check");
  });

  it("does NOT include the prior-attempt note when priorAttemptOps is empty (the original build, not a retry)", () => {
    const r = report({ geometricIssues: [issue("connectivity", "x is disconnected")] });
    const msg = buildCorrectionMessage(r, 1, 2, []);
    expect(msg).not.toContain("LAST correction attempt");
  });

  it("includes the prior-attempt note, with the exact op, when a retry's own instance_ops are passed", () => {
    // 2026-07-26 live repro: an identical move_instance retried verbatim across both correction
    // rounds burned the whole auto-correct budget on a no-op -- this is the fix.
    const r = report({ geometricIssues: [issue("connectivity", "rail_3 is disconnected")] });
    const priorOps: InstanceOp[] = [
      { op: "move_instance", instance_id: "rail_3", x_mm: 45, y_mm: -45, z_mm: 50 },
    ];
    const msg = buildCorrectionMessage(r, 2, 2, priorOps);
    expect(msg).toContain("LAST correction attempt already tried exactly this");
    expect(msg).toContain("- move_instance rail_3 to (45, -45, 50)");
    expect(msg).toContain("do NOT repeat the");
    expect(msg).toContain("(auto-correction round 2 of 2)");
  });

  it("formats a remove_instance prior op without a position (no x_mm on that op kind)", () => {
    const r = report({ geometricIssues: [issue("degeneracy", "still broken")] });
    const priorOps: InstanceOp[] = [{ op: "remove_instance", instance_id: "desk_stand" }];
    const msg = buildCorrectionMessage(r, 2, 2, priorOps);
    expect(msg).toContain("- remove_instance desk_stand");
    expect(msg).not.toContain("to (");
  });

  it("lists multiple prior ops, one per line", () => {
    const r = report({ geometricIssues: [issue("interference", "still overlapping")] });
    const priorOps: InstanceOp[] = [
      { op: "move_instance", instance_id: "rail_1", x_mm: 45, y_mm: 45, z_mm: 50 },
      { op: "move_instance", instance_id: "rail_2", x_mm: -45, y_mm: 45, z_mm: 50 },
    ];
    const msg = buildCorrectionMessage(r, 2, 2, priorOps);
    expect(msg).toContain("- move_instance rail_1 to (45, 45, 50)");
    expect(msg).toContain("- move_instance rail_2 to (-45, 45, 50)");
  });

  it("includes the visual-check corroboration note only when a visual issue is present", () => {
    const r = report({
      geometricIssues: [],
      visual: { ok: false, issues: [issue("visual", "camera looks embedded")], summary: "" },
    });
    const msg = buildCorrectionMessage(r, 1, 2, []);
    expect(msg).toContain("- camera looks embedded");
    expect(msg).toContain("VISUAL check");
    expect(msg).toContain("cross-check it against the geometric findings");
  });

  it("does not include the visual note when there are no visual issues", () => {
    const r = report({ geometricIssues: [issue("connectivity", "x is disconnected")] });
    const msg = buildCorrectionMessage(r, 1, 2, []);
    expect(msg).not.toContain("VISUAL check");
  });

  it("includes BOTH the prior-attempt and visual notes together when both apply", () => {
    const r = report({
      geometricIssues: [issue("connectivity", "still disconnected")],
      visual: { ok: false, issues: [issue("visual", "looks off")], summary: "" },
    });
    const priorOps: InstanceOp[] = [{ op: "move_instance", instance_id: "rail_1", x_mm: 0, y_mm: 0, z_mm: 0 }];
    const msg = buildCorrectionMessage(r, 2, 2, priorOps);
    expect(msg).toContain("LAST correction attempt already tried exactly this");
    expect(msg).toContain("VISUAL check");
  });
});
