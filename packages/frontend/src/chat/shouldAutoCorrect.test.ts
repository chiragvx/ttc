import { describe, expect, it } from "vitest";
import { shouldAutoCorrect } from "./shouldAutoCorrect";
import type { ValidationIssue, ValidationResult } from "../types";

function report(overrides: Partial<ValidationResult> & { geometricIssues?: ValidationIssue[] } = {}): ValidationResult {
  const { geometricIssues, ...rest } = overrides;
  return {
    ok: true,
    geometric: { ok: true, issues: geometricIssues ?? [], summary: "" },
    visual: null,
    vision_enabled: false,
    vision_ran: false,
    ...rest,
  };
}

function issue(check: string, severity: string): ValidationIssue {
  return { check, severity, message: `${check} issue`, instances: ["x"] };
}

describe("shouldAutoCorrect", () => {
  it("fires on !report.ok (the existing degeneracy case) even with no issues listed", () => {
    expect(shouldAutoCorrect(report({ ok: false }))).toBe(true);
  });

  it("fires on a connectivity issue even when report.ok is true", () => {
    // 2026-07-20 fix: connectivity is severity=warning, so report.ok stays true -- this is the exact
    // case that used to silently never trigger auto-correction.
    const r = report({ ok: true, geometricIssues: [issue("connectivity", "warning")] });
    expect(shouldAutoCorrect(r)).toBe(true);
  });

  it("does NOT fire on an embedding-only issue -- ambiguous by design, never auto-corrected", () => {
    const r = report({ ok: true, geometricIssues: [issue("embedding", "info")] });
    expect(shouldAutoCorrect(r)).toBe(false);
  });

  it("does not fire when there are no issues at all", () => {
    expect(shouldAutoCorrect(report())).toBe(false);
  });

  it("checks the visual report's issues too, not just geometric", () => {
    const r = report({ ok: true, visual: { ok: true, issues: [issue("connectivity", "warning")], summary: "" } });
    expect(shouldAutoCorrect(r)).toBe(true);
  });
});
