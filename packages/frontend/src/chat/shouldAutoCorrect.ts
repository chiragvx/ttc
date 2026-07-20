import type { ValidationResult } from "../types";

// 2026-07-20 — the self-check kept correctly reporting "connectivity" (disconnected parts) issues
// turn after turn, but the copilot never acted on them: Chat.tsx used to gate the auto-correct loop
// on bare `!report.ok`, and packages/truth_plane/validate.py's `ok` is only false when an "error"
// -severity issue exists (degeneracy only) — connectivity is hardcoded "warning", so it never flipped
// `ok` and the auto-correct block never ran. Extracted as its own pure function (mirrors
// summarizeOutcomes.ts's own "extract the risky pure logic, test it directly" precedent) so this is
// unit-testable without mounting the whole Chat component.
//
// Deliberately does NOT include "embedding" issues: a part sitting entirely inside another is
// genuinely ambiguous (could be a legitimate internal component — a battery, a spar, a payload) —
// validate.py's own design keeps that at "info" severity and never auto-corrects it, since a false
// "move it outside" correction would be worse than leaving it for a human to judge. This mirrors
// that same restraint at the trigger-gate level, not just the severity level.
export function shouldAutoCorrect(report: ValidationResult): boolean {
  if (!report.ok) return true;
  const issues = [...report.geometric.issues, ...(report.visual?.issues ?? [])];
  return issues.some((i) => i.check === "connectivity");
}
