import type { ConnectionOp, CouplingOp, FeatureOp, InstanceOp, ParameterDelta, ValidationResult } from "../types";

// 2026-07-26 — extracted from Chat.tsx's inline string-building (mirrors shouldAutoCorrect.ts's own
// "extract the risky pure logic, test it directly" precedent) so this is unit-testable without
// mounting the whole Chat component.
//
// `priorAttempt` buckets every op kind the IMMEDIATELY PRECEDING turn proposed, but ONLY when that
// turn was itself a correction attempt that still left the self-check failing -- the caller (Chat.tsx)
// passes `NO_PRIOR_ATTEMPT` (every bucket empty) when this round's message is for the ORIGINAL build,
// not a retry, so the "you already tried this" note never fires on a build's own first-pass ops.
//
// Confirmed live (2026-07-26), twice, in one session: the cubesat test retried an identical
// `move_instance` verbatim across both correction rounds; the soldering-stand test retried an
// identical `remove_instance` verbatim. Both burned the ENTIRE 2-round auto-correct budget on a pure
// no-op, because nothing told the model "the issues above are the SAME ones your last fix was
// supposed to resolve, and it didn't" -- the model had the ops in its own conversation history but
// never connected "this is the same fix I already tried."
//
// 2026-08-03 — that same gap was ALSO real for every other op kind: only instance_ops were ever
// captured (Chat.tsx used to track a single `thisTurnInstanceOps` array), so an identical
// delta/feature_op/connection_op/coupling_op retried verbatim got NO signal at all, prose or
// otherwise -- nothing about the "retried a failed fix verbatim" failure mode is instance_op-specific.
// `PriorAttempt` covers every op kind Chat.tsx's proposal loop can apply (excluding fit_ops/
// join_annotation_ops, which aren't part of this defect), so the same "here is exactly what you
// tried, it didn't work, don't repeat it" note fires no matter which op kind the failed fix used.
export interface PriorAttempt {
  deltas: ParameterDelta[];
  featureOps: FeatureOp[];
  instanceOps: InstanceOp[];
  connectionOps: ConnectionOp[];
  couplingOps: CouplingOp[];
}

export const NO_PRIOR_ATTEMPT: PriorAttempt = {
  deltas: [],
  featureOps: [],
  instanceOps: [],
  connectionOps: [],
  couplingOps: [],
};

function formatDelta(d: ParameterDelta): string {
  return `- set ${d.target_node} = ${d.requested_value}`;
}

function formatInstanceOp(op: InstanceOp): string {
  return `- ${op.op} ${op.instance_id ?? "(new)"}` +
    (op.x_mm != null ? ` to (${op.x_mm}, ${op.y_mm}, ${op.z_mm})` : "");
}

function formatFeatureOp(op: FeatureOp): string {
  return `- ${op.op} on ${op.instance_id} ${op.feature_id ?? "(new feature)"}`;
}

function formatConnectionOp(op: ConnectionOp): string {
  return op.op === "add_connection"
    ? `- add_connection ${op.a_instance}.${op.a_interface} <-> ${op.b_instance}.${op.b_interface}`
    : `- remove_connection ${op.id}`;
}

function formatCouplingOp(op: CouplingOp): string {
  return op.op === "add_coupling"
    ? `- add_coupling ${op.target_instance} <- ${op.relation}`
    : `- remove_coupling ${op.id}`;
}

export function buildCorrectionMessage(
  report: ValidationResult,
  round: number,
  maxRounds: number,
  priorAttempt: PriorAttempt,
): string {
  const geomIssues = report.geometric.issues;
  // "structural" (2026-08-03) — the coarse coupling-derived FS estimate, same report field
  // shouldAutoCorrect.ts now gates on. Listed here UNFILTERED by severity, same as geomIssues above
  // (which includes non-triggering checks like "embedding" too) — once a correction round is
  // triggered for ANY reason, the model gets the full picture, not just the one finding that fired
  // the gate. A passing FS ("info") or an "no bending-stress model for this output yet" disclosure
  // sitting alongside a genuine FS<1.0 warning is useful context, not noise.
  const structuralIssues = report.structural.issues;
  const visualIssues = report.visual?.issues ?? [];
  const issues = [...geomIssues, ...structuralIssues, ...visualIssues];
  const lines = issues.map((i) => `- ${i.message}`).join("\n");
  let correction =
    `Self-check of what you just built found problems:\n${lines}\n\n` +
    `Fix them — adjust the parts/params so the design validates. ` +
    `(auto-correction round ${round} of ${maxRounds})`;

  // one line per prior op, across every op kind -- enough for the model to recognize "I already did
  // this" without bloating the correction turn with a full JSON dump.
  const priorLines = [
    ...priorAttempt.deltas.map(formatDelta),
    ...priorAttempt.instanceOps.map(formatInstanceOp),
    ...priorAttempt.featureOps.map(formatFeatureOp),
    ...priorAttempt.connectionOps.map(formatConnectionOp),
    ...priorAttempt.couplingOps.map(formatCouplingOp),
  ];
  if (priorLines.length > 0) {
    correction += `\n\nNote: the LAST correction attempt already tried exactly this:\n${priorLines.join("\n")}\n` +
      `The issues above are STILL present, so that exact fix did not work — do NOT repeat the ` +
      `same op(s) with the same values again. Diagnose why it failed (wrong values? the wrong ` +
      `op entirely? a different part actually at fault?) and try a genuinely different ` +
      `approach, or say plainly that you're unsure how to fix it rather than reissuing an ` +
      `identical attempt.`;
  }

  if (visualIssues.length > 0) {
    // the vision judge's verdict is diagnostic, never authoritative on its own (mirrors the "convert
    // every visual concern into a deterministic check" discipline) -- don't let the model treat a
    // visual-only claim as ground truth for what to change without checking it against the actual
    // geometric findings/live positions first.
    correction += `\n\nNote: some of the issues above came from the VISUAL check (a vision ` +
      `model's judgment of a rendered image), not the geometric self-check — it is a useful ` +
      `signal but not ground truth. Before proposing a fix for a visual-only finding, ` +
      `cross-check it against the geometric findings and the real instance positions in the ` +
      `current ledger; don't change geometry based on the vision text alone if it doesn't ` +
      `line up with what the geometric checks and live positions actually show.`;
  }

  return correction;
}
