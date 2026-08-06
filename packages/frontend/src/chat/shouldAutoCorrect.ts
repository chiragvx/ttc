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
  const issues = [...report.geometric.issues, ...report.structural.issues, ...(report.visual?.issues ?? [])];
  // "connections" (dangling/self/unsatisfied connection refs, from connection_issues() in
  // packages/subsystems/placement.py) is the same class of confident, actionable signal as
  // "connectivity" above -- validate.py's own comment calls an unresolved connection "a real
  // error", not an ambiguous judgment call -- it's just hardcoded severity="warning" there too,
  // so it needs the same override of the !report.ok gate.
  //
  // "interference" (2026-07-22, validate.py) -- two comparably-sized parts truly interpenetrating
  // with no declared connection between them. Unlike "embedding" (deliberately excluded above --
  // a much-smaller part fully inside a bigger one is genuinely ambiguous), two comparable-sized
  // unrelated parts occupying the same space is not ambiguous the same way -- it's the coincident-
  // bracket failure this check exists to catch, so it belongs in the confident/actionable group.
  //
  // "fit" (2026-07-27, validate.py::fit_drift_findings) -- a connector's stored dimensions no
  // longer match what its host's CURRENT cross-section implies (the host was resized after the fit
  // was wired). A confident, actionable, quantified mismatch -- the same class as "interference"
  // above, not an ambiguous judgment call -- and the fix is a single well-defined op (resync_fit),
  // so this must drive the self-correct loop the same way; a mechanism the copilot never learns to
  // invoke is dead plumbing (keepout_mm's own fate -- fully built, zero adopters, precisely because
  // nothing ever taught the model to call it or wired it into this trigger set).
  //
  // "structural" (2026-08-03, packages/transport/app.py::_coarse_structural_summary) -- a coarse,
  // closed-form cantilever-over-bounding-box FS estimate for any instance carrying a coupling-derived
  // load. This is the ONLY safety-shaped signal the self-check produces (Inversion #1: "a missing
  // safety input is unknown and BLOCKS export -- never a fabricated green light"), and until now it
  // was the one signal this trigger set ignored entirely -- an instance reporting FS≈0.3 against its
  // own derived load sat in the ledger, self-check "ok", nothing in this file ever seeing it.
  //
  // The severity check here is load-bearing, not decoration: `_coarse_structural_summary` deliberately
  // reports EVERY coupled+buildable instance, not just failing ones, and gives "structural" issues a
  // MIXED severity unlike every check above -- "warning" only when the crude estimate itself reads
  // FS < 1.0 (drastically undersized for its derived load); "info" both for a passing estimate AND for
  // the separate "N coupling(s) derived but this coarse check has no bending-stress model for that
  // output yet" disclosure. Firing on check === "structural" alone -- not gated on severity -- would
  // trip this file's own top-of-file lesson from the other direction: a trigger so broad it fires on
  // findings nothing can act on (a passing FS, or a plain "can't estimate this one yet" notice) burns
  // the auto-correct budget on a no-op round after round, same wasted-loop shape as the connectivity
  // gap this file was originally built to close, just from being too broad instead of too narrow.
  // Gating on severity === "warning" keeps this exactly as narrow as the confident/actionable group
  // above: FS < 1.0, and nothing else.
  //
  // "envelope_drift" (2026-08-06, validate.py::_envelope_drift_findings) -- a housing-family
  // instance (declares envelope_socket) whose `wraps` fully resolves but whose OWN stored dims no
  // longer match what a FRESH compute_envelope call implies -- the wrapped group moved/resized since
  // the housing was last derived. Always hardcoded severity="warning" in validate.py (never gated
  // further here, unlike "structural" above), a confident quantified mismatch with a single
  // well-defined fix (resync_envelope), same class as "fit"'s own resync_fit precedent -- both
  // function docstrings and packages/transport/app.py's own docstring already assert this finding
  // "drives the auto-correct loop's resync_envelope suggestion"; leaving it out of this set here
  // would make that claim false and repeat the exact keepout_mm dead-plumbing lesson cited above --
  // a mechanism the copilot never learns to invoke because nothing in this file ever fires on it.
  return issues.some((i) =>
    i.check === "connectivity" ||
    i.check === "connections" ||
    i.check === "interference" ||
    i.check === "fit" ||
    i.check === "envelope_drift" ||
    (i.check === "structural" && i.severity === "warning"),
  );
}
