import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RequirementsData } from "./api";
import { RequirementsCard } from "./RequirementsCard";

function makeData(overrides: Partial<RequirementsData> = {}): RequirementsData {
  return {
    goal_set: true,
    implied_fs_floor: null,
    enforced_fs_floor: 1.5,
    implied_load_n: null,
    satisfied: 0,
    total: 0,
    requirements: [],
    metrics: {},
    ...overrides,
  };
}

describe("RequirementsCard", () => {
  it("prompts to state a goal when none is set", () => {
    render(<RequirementsCard data={null} onOptimize={vi.fn()} />);
    expect(screen.getByText(/state a goal in chat/i)).toBeInTheDocument();
  });

  it("renders each requirement row with its live status", () => {
    const data = makeData({
      satisfied: 1,
      total: 2,
      requirements: [
        { id: "R1", text: "factor of safety >= 2", metric: "factor_of_safety", op: ">=", target: 2,
          method: "ANALYSIS", status: "SATISFIED", value: 2.4 },
        { id: "R2", text: "mass <= 30 g", metric: "mass_g", op: "<=", target: 30,
          method: "TEST", status: "VIOLATED", value: 45 },
      ],
    });
    render(<RequirementsCard data={data} onOptimize={vi.fn()} />);
    expect(screen.getByText("factor of safety >= 2")).toBeInTheDocument();
    expect(screen.getByText("mass <= 30 g")).toBeInTheDocument();
    expect(screen.getByText("1/2 met")).toBeInTheDocument();
  });

  it("shows the FS-floor line only when the goal implies one", () => {
    const { rerender } = render(<RequirementsCard data={makeData()} onOptimize={vi.fn()} />);
    expect(screen.queryByText(/goal demands fs/i)).not.toBeInTheDocument();

    rerender(<RequirementsCard data={makeData({ implied_fs_floor: 2 })} onOptimize={vi.fn()} />);
    expect(screen.getByText(/goal demands fs ≥ 2; the export gate now enforces fs ≥ 1.5/i)).toBeInTheDocument();
  });

  it("shows the stated-load line only when the goal implies one (2026-07-15 load-threading fix)", () => {
    const { rerender } = render(<RequirementsCard data={makeData()} onOptimize={vi.fn()} />);
    expect(screen.queryByText(/stated .* n load/i)).not.toBeInTheDocument();

    rerender(<RequirementsCard data={makeData({ implied_load_n: 200 })} onOptimize={vi.fn()} />);
    expect(screen.getByText(/analysis now runs against the stated 200 n load/i)).toBeInTheDocument();
  });

  it("offers to optimize only when FS is unmet, and wires the click through", () => {
    const onOptimize = vi.fn();
    const unmet = makeData({
      requirements: [{ id: "R1", text: "factor of safety >= 2", metric: "factor_of_safety", op: ">=",
                      target: 2, method: "ANALYSIS", status: "VIOLATED", value: 1.1 }],
    });
    render(<RequirementsCard data={unmet} onOptimize={onOptimize} />);
    const button = screen.getByRole("button", { name: /find the lightest design/i });
    fireEvent.click(button);
    expect(onOptimize).toHaveBeenCalledOnce();
  });

  it("hides the optimize button once FS is satisfied", () => {
    const met = makeData({
      requirements: [{ id: "R1", text: "factor of safety >= 2", metric: "factor_of_safety", op: ">=",
                      target: 2, method: "ANALYSIS", status: "SATISFIED", value: 2.4 }],
    });
    render(<RequirementsCard data={met} onOptimize={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /find the lightest design/i })).not.toBeInTheDocument();
  });
});
