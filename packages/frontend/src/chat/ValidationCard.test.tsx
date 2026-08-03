import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ValidationCard } from "./ValidationCard";
import type { ValidationIssue, ValidationResult } from "../types";

function issue(over: Partial<ValidationIssue> = {}): ValidationIssue {
  return { check: "structural", severity: "info", message: "leg_fl: FS≈2.30", instances: ["leg_fl"], ...over };
}

function report(overrides: Partial<ValidationResult> = {}): ValidationResult {
  return {
    ok: true,
    geometric: { ok: true, issues: [], summary: "" },
    structural: { ok: true, issues: [], summary: "" },
    visual: null,
    vision_enabled: false,
    vision_ran: false,
    ...overrides,
  };
}

describe("ValidationCard structural section", () => {
  it("renders nothing structural when there are no coupled parts", () => {
    render(<ValidationCard result={report()} />);
    expect(screen.queryByText(/coarse estimate/i)).not.toBeInTheDocument();
  });

  it("renders a structural info finding without affecting the passed banner", () => {
    const result = report({ structural: { ok: true, issues: [issue()], summary: "coarse estimate for 1 part" } });
    render(<ValidationCard result={result} />);
    expect(screen.getByText(/self-check passed/i)).toBeInTheDocument();
    expect(screen.getByText(/coarse estimate/i)).toBeInTheDocument();
    expect(screen.getByText(/leg_fl: FS≈2.30/)).toBeInTheDocument();
  });

  it("still shows Self-check passed even when a structural WARNING (fs<1.0) is present", () => {
    // structural findings are informational (a real number, not a defect) -- they must never flip
    // the pass/fail banner, which is reserved for geometric/visual defects the auto-correct loop acts on.
    const result = report({
      structural: {
        ok: true,
        issues: [issue({ severity: "warning", message: "leg_fl: FS≈0.42 -- looks undersized" })],
        summary: "coarse estimate for 1 part",
      },
    });
    render(<ValidationCard result={result} />);
    expect(screen.getByText(/self-check passed/i)).toBeInTheDocument();
    expect(screen.getByText(/FS≈0.42/)).toBeInTheDocument();
  });

  it("does not trigger the 'found issues' banner from structural alone, but still does from a real geometric issue", () => {
    const result = report({
      geometric: { ok: true, issues: [{ check: "connectivity", severity: "warning", message: "floating", instances: ["x"] }], summary: "" },
      structural: { ok: true, issues: [issue()], summary: "" },
    });
    render(<ValidationCard result={result} />);
    expect(screen.getByText(/self-check found issues/i)).toBeInTheDocument();
  });

  it("renders multiple structural findings, one per coupled instance", () => {
    const result = report({
      structural: {
        ok: true,
        issues: [issue({ instances: ["leg_fl"] }), issue({ instances: ["leg_fr"], message: "leg_fr: FS≈2.10" })],
        summary: "",
      },
    });
    render(<ValidationCard result={result} />);
    expect(screen.getByText(/leg_fl: FS≈2.30/)).toBeInTheDocument();
    expect(screen.getByText(/leg_fr: FS≈2.10/)).toBeInTheDocument();
  });
});
