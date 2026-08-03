import { describe, expect, it } from "vitest";
import { buildCorrectionMessage, NO_PRIOR_ATTEMPT, type PriorAttempt } from "./buildCorrectionMessage";
import type { ConnectionOp, CouplingOp, FeatureOp, InstanceOp, ParameterDelta, ValidationIssue, ValidationResult } from "../types";

function report(
  overrides: Partial<ValidationResult> & { geometricIssues?: ValidationIssue[]; structuralIssues?: ValidationIssue[] } = {},
): ValidationResult {
  const { geometricIssues, structuralIssues, ...rest } = overrides;
  return {
    ok: false,
    geometric: { ok: false, issues: geometricIssues ?? [], summary: "" },
    structural: { ok: true, issues: structuralIssues ?? [], summary: "" },
    visual: null,
    vision_enabled: false,
    vision_ran: false,
    ...rest,
  };
}

function issue(check: string, message: string, severity: string = "warning"): ValidationIssue {
  return { check, severity, message, instances: ["x"] };
}

function priorAttempt(overrides: Partial<PriorAttempt>): PriorAttempt {
  return { ...NO_PRIOR_ATTEMPT, ...overrides };
}

describe("buildCorrectionMessage", () => {
  it("builds the base message with round/max and every issue listed, with no prior-attempt note", () => {
    const r = report({ geometricIssues: [issue("connectivity", "rail_1 is disconnected")] });
    const msg = buildCorrectionMessage(r, 1, 2, NO_PRIOR_ATTEMPT);
    expect(msg).toContain("Self-check of what you just built found problems:");
    expect(msg).toContain("- rail_1 is disconnected");
    expect(msg).toContain("(auto-correction round 1 of 2)");
    expect(msg).not.toContain("already tried");
    expect(msg).not.toContain("VISUAL check");
  });

  it("does NOT include the prior-attempt note when priorAttempt is all-empty (the original build, not a retry)", () => {
    const r = report({ geometricIssues: [issue("connectivity", "x is disconnected")] });
    const msg = buildCorrectionMessage(r, 1, 2, NO_PRIOR_ATTEMPT);
    expect(msg).not.toContain("LAST correction attempt");
  });

  it("includes a structural FS < 1.0 finding's message text in the issue list", () => {
    // 2026-08-03: the coarse structural self-check is the only safety-shaped signal produced --
    // it must actually reach the correction message, not just the shouldAutoCorrect gate.
    const r = report({
      geometricIssues: [],
      structuralIssues: [issue("structural", "leg_1: coarse pre-check gives FS≈0.42.", "warning")],
    });
    const msg = buildCorrectionMessage(r, 1, 2, NO_PRIOR_ATTEMPT);
    expect(msg).toContain("- leg_1: coarse pre-check gives FS≈0.42.");
  });

  it("includes an info-severity structural finding's text too (full context, not just the trigger)", () => {
    // mirrors geomIssues' own existing behavior (e.g. embedding, which never triggers on its own but
    // is still listed when present alongside a triggering issue) -- once a correction round fires,
    // the model gets the full self-check picture.
    const r = report({
      geometricIssues: [issue("connectivity", "rail_2 is disconnected")],
      structuralIssues: [issue("structural", "leg_2: coarse pre-check gives FS≈3.10.", "info")],
    });
    const msg = buildCorrectionMessage(r, 1, 2, NO_PRIOR_ATTEMPT);
    expect(msg).toContain("- leg_2: coarse pre-check gives FS≈3.10.");
  });

  it("includes the prior-attempt note, with the exact op, when a retry's own instance_ops are passed", () => {
    // 2026-07-26 live repro: an identical move_instance retried verbatim across both correction
    // rounds burned the whole auto-correct budget on a no-op -- this is the fix.
    const r = report({ geometricIssues: [issue("connectivity", "rail_3 is disconnected")] });
    const priorOps: InstanceOp[] = [
      { op: "move_instance", instance_id: "rail_3", x_mm: 45, y_mm: -45, z_mm: 50 },
    ];
    const msg = buildCorrectionMessage(r, 2, 2, priorAttempt({ instanceOps: priorOps }));
    expect(msg).toContain("LAST correction attempt already tried exactly this");
    expect(msg).toContain("- move_instance rail_3 to (45, -45, 50)");
    expect(msg).toContain("do NOT repeat the");
    expect(msg).toContain("(auto-correction round 2 of 2)");
  });

  it("formats a remove_instance prior op without a position (no x_mm on that op kind)", () => {
    const r = report({ geometricIssues: [issue("degeneracy", "still broken")] });
    const priorOps: InstanceOp[] = [{ op: "remove_instance", instance_id: "desk_stand" }];
    const msg = buildCorrectionMessage(r, 2, 2, priorAttempt({ instanceOps: priorOps }));
    expect(msg).toContain("- remove_instance desk_stand");
    expect(msg).not.toContain("to (");
  });

  it("lists multiple prior ops, one per line", () => {
    const r = report({ geometricIssues: [issue("interference", "still overlapping")] });
    const priorOps: InstanceOp[] = [
      { op: "move_instance", instance_id: "rail_1", x_mm: 45, y_mm: 45, z_mm: 50 },
      { op: "move_instance", instance_id: "rail_2", x_mm: -45, y_mm: 45, z_mm: 50 },
    ];
    const msg = buildCorrectionMessage(r, 2, 2, priorAttempt({ instanceOps: priorOps }));
    expect(msg).toContain("- move_instance rail_1 to (45, 45, 50)");
    expect(msg).toContain("- move_instance rail_2 to (-45, 45, 50)");
  });

  it("includes a repeated identical DELTA in the prior-attempt note (not just instance_ops)", () => {
    // 2026-08-03: only instance_ops used to be captured -- an identical delta retried verbatim got
    // no signal at all.
    const r = report({ geometricIssues: [issue("structural", "leg_1 still undersized")] });
    const priorDeltas: ParameterDelta[] = [{ target_node: "leg_1.thickness_mm", requested_value: 4 }];
    const msg = buildCorrectionMessage(r, 2, 2, priorAttempt({ deltas: priorDeltas }));
    expect(msg).toContain("LAST correction attempt already tried exactly this");
    expect(msg).toContain("- set leg_1.thickness_mm = 4");
  });

  it("includes a repeated identical FEATURE_OP in the prior-attempt note", () => {
    const r = report({ geometricIssues: [issue("degeneracy", "still broken")] });
    const priorFeatureOps: FeatureOp[] = [
      { op: "add_feature", instance_id: "plate_1", kind: "hole", shape: "circle", dia_mm: 5 },
    ];
    const msg = buildCorrectionMessage(r, 2, 2, priorAttempt({ featureOps: priorFeatureOps }));
    expect(msg).toContain("- add_feature on plate_1 (new feature)");
  });

  it("includes a repeated identical CONNECTION_OP in the prior-attempt note", () => {
    const r = report({ geometricIssues: [issue("connections", "still dangling")] });
    const priorConnectionOps: ConnectionOp[] = [
      { op: "add_connection", a_instance: "rail_1", a_interface: "end_a", b_instance: "rail_2", b_interface: "end_b" },
    ];
    const msg = buildCorrectionMessage(r, 2, 2, priorAttempt({ connectionOps: priorConnectionOps }));
    expect(msg).toContain("- add_connection rail_1.end_a <-> rail_2.end_b");
  });

  it("includes a repeated identical COUPLING_OP in the prior-attempt note", () => {
    const r = report({ geometricIssues: [issue("structural", "still undersized")] });
    const priorCouplingOps: CouplingOp[] = [{ op: "add_coupling", target_instance: "leg_1", relation: "tip_load_from_mass" }];
    const msg = buildCorrectionMessage(r, 2, 2, priorAttempt({ couplingOps: priorCouplingOps }));
    expect(msg).toContain("- add_coupling leg_1 <- tip_load_from_mass");
  });

  it("lists prior ops across MULTIPLE kinds together in one note", () => {
    const r = report({ geometricIssues: [issue("interference", "still overlapping")] });
    const attempt = priorAttempt({
      deltas: [{ target_node: "leg_1.thickness_mm", requested_value: 4 }],
      instanceOps: [{ op: "move_instance", instance_id: "rail_1", x_mm: 0, y_mm: 0, z_mm: 0 }],
    });
    const msg = buildCorrectionMessage(r, 2, 2, attempt);
    expect(msg).toContain("- set leg_1.thickness_mm = 4");
    expect(msg).toContain("- move_instance rail_1 to (0, 0, 0)");
  });

  it("includes the visual-check corroboration note only when a visual issue is present", () => {
    const r = report({
      geometricIssues: [],
      visual: { ok: false, issues: [issue("visual", "camera looks embedded")], summary: "" },
    });
    const msg = buildCorrectionMessage(r, 1, 2, NO_PRIOR_ATTEMPT);
    expect(msg).toContain("- camera looks embedded");
    expect(msg).toContain("VISUAL check");
    expect(msg).toContain("cross-check it against the geometric findings");
  });

  it("does not include the visual note when there are no visual issues", () => {
    const r = report({ geometricIssues: [issue("connectivity", "x is disconnected")] });
    const msg = buildCorrectionMessage(r, 1, 2, NO_PRIOR_ATTEMPT);
    expect(msg).not.toContain("VISUAL check");
  });

  it("includes BOTH the prior-attempt and visual notes together when both apply", () => {
    const r = report({
      geometricIssues: [issue("connectivity", "still disconnected")],
      visual: { ok: false, issues: [issue("visual", "looks off")], summary: "" },
    });
    const priorOps: InstanceOp[] = [{ op: "move_instance", instance_id: "rail_1", x_mm: 0, y_mm: 0, z_mm: 0 }];
    const msg = buildCorrectionMessage(r, 2, 2, priorAttempt({ instanceOps: priorOps }));
    expect(msg).toContain("LAST correction attempt already tried exactly this");
    expect(msg).toContain("VISUAL check");
  });
});
