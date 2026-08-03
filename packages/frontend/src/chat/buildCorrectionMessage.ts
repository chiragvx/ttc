import type { InstanceOp, ValidationResult } from "../types";

// 2026-07-26 — extracted from Chat.tsx's inline string-building (mirrors shouldAutoCorrect.ts's own
// "extract the risky pure logic, test it directly" precedent) so this is unit-testable without
// mounting the whole Chat component.
//
// `priorAttemptOps` is the instance_ops the IMMEDIATELY PRECEDING turn proposed, but ONLY when that
// turn was itself a correction attempt that still left the self-check failing -- the caller (Chat.tsx)
// passes `[]` when this round's message is for the ORIGINAL build, not a retry, so the "you already
// tried this" note never fires on a build's own first-pass instance_ops.
//
// Confirmed live (2026-07-26), twice, in one session: the cubesat test retried an identical
// `move_instance` verbatim across both correction rounds; the soldering-stand test retried an
// identical `remove_instance` verbatim. Both burned the ENTIRE 2-round auto-correct budget on a pure
// no-op, because nothing told the model "the issues above are the SAME ones your last fix was
// supposed to resolve, and it didn't" -- the model had the ops in its own conversation history but
// never connected "this is the same fix I already tried."
export function buildCorrectionMessage(
  report: ValidationResult,
  round: number,
  maxRounds: number,
  priorAttemptOps: InstanceOp[],
): string {
  const geomIssues = report.geometric.issues;
  const visualIssues = report.visual?.issues ?? [];
  const issues = [...geomIssues, ...visualIssues];
  const lines = issues.map((i) => `- ${i.message}`).join("\n");
  let correction =
    `Self-check of what you just built found problems:\n${lines}\n\n` +
    `Fix them — adjust the parts/params so the design validates. ` +
    `(auto-correction round ${round} of ${maxRounds})`;

  if (priorAttemptOps.length > 0) {
    // one line per prior op, not a full JSON dump -- enough for the model to recognize "I already
    // did this" without bloating the correction turn.
    const priorOps = priorAttemptOps
      .map((op) => `- ${op.op} ${op.instance_id ?? "(new)"}` +
        (op.x_mm != null ? ` to (${op.x_mm}, ${op.y_mm}, ${op.z_mm})` : ""))
      .join("\n");
    correction += `\n\nNote: the LAST correction attempt already tried exactly this:\n${priorOps}\n` +
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
