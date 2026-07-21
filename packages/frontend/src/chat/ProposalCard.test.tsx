import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProposalCard } from "./ProposalCard";
import type { DeltaOutcome } from "../types";

// foundations-audit H6 (2026-07-21): the caller used to mark a delta undo "undone" unconditionally,
// even when the backend REJECTED/CONFLICTed the reversal — this pins the presentational half of the
// fix: an undoError must render (never a silent "↩ undone"), and once undone actually succeeds, the
// error clears and the button reflects a real success.

function outcome(overrides: Partial<DeltaOutcome> = {}): DeltaOutcome {
  return {
    node: "instances.root.params.skin_thickness_mm",
    requested: 3.0,
    applied: 3.0,
    oldValue: 2.0,
    status: "APPLIED",
    ...overrides,
  };
}

describe("ProposalCard", () => {
  it("shows the real 'undone' state when the undo actually succeeded", () => {
    render(<ProposalCard outcomes={[outcome()]} onUndo={() => {}} undone={true} onHover={undefined} />);
    expect(screen.getByRole("button", { name: /undone/i })).toBeDisabled();
    expect(screen.queryByText(/rejected|conflict|hard_lock/i)).not.toBeInTheDocument();
  });

  it("surfaces the backend's rejection reason instead of quietly claiming success", () => {
    render(
      <ProposalCard
        outcomes={[outcome()]}
        onUndo={() => {}}
        undone={false}
        undoError="skin_thickness_mm: node is HARD_LOCK'd"
        onHover={undefined}
      />,
    );
    expect(screen.getByText(/hard_lock/i)).toBeInTheDocument();
    // the button must NOT read "undone" just because an undo was attempted -- it stays actionable
    expect(screen.getByRole("button", { name: /retry undo/i })).not.toBeDisabled();
  });

  it("clicking undo calls back through to the caller, which decides success/failure", () => {
    const onUndo = vi.fn();
    render(<ProposalCard outcomes={[outcome()]} onUndo={onUndo} undone={false} onHover={undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /undo/i }));
    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it("renders no undo button at all when nothing in the batch is actually revertible", () => {
    render(
      <ProposalCard
        outcomes={[outcome({ status: "REJECTED", oldValue: null, applied: null })]}
        onUndo={() => {}}
        undone={false}
        onHover={undefined}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
