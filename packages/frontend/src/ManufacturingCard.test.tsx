import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ManufacturingCard } from "./ManufacturingCard";
import type { ManufacturingManifest } from "./types";

function makeData(overrides: Partial<ManufacturingManifest> = {}): ManufacturingManifest {
  return {
    material: "PLA",
    parts: [],
    assembly_steps: [],
    ...overrides,
  };
}

describe("ManufacturingCard", () => {
  it("shows an empty-state message when there is no manifest yet", () => {
    render(<ManufacturingCard data={null} />);
    expect(screen.getByText(/no manufacturing manifest yet/i)).toBeInTheDocument();
  });

  it("shows an empty-state message when the manifest has no parts", () => {
    render(<ManufacturingCard data={makeData()} />);
    expect(screen.getByText(/no manufacturing manifest yet/i)).toBeInTheDocument();
  });

  it("renders material/process per part and the assembly steps when populated", () => {
    const data = makeData({
      material: "Aluminum 6061",
      parts: [
        { instance_id: "i1", subsystem_type: "bracket", material: "Aluminum 6061", process: "CNC" },
        { instance_id: "i2", subsystem_type: "enclosure", material: "PETG", process: "print" },
      ],
      assembly_steps: ["Mount bracket to base", "Fasten enclosure to bracket"],
    });
    render(<ManufacturingCard data={data} />);

    expect(screen.getByText("2 parts")).toBeInTheDocument();
    expect(screen.getByText("bracket")).toBeInTheDocument();
    expect(screen.getByText("enclosure")).toBeInTheDocument();
    expect(screen.getByText("CNC")).toBeInTheDocument();
    expect(screen.getByText("print")).toBeInTheDocument();
    expect(screen.getByText("Mount bracket to base")).toBeInTheDocument();
    expect(screen.getByText("Fasten enclosure to bracket")).toBeInTheDocument();
  });

  it("uses singular part count for exactly one part", () => {
    const data = makeData({
      parts: [{ instance_id: "i1", subsystem_type: "bracket", material: "PLA", process: "print" }],
    });
    render(<ManufacturingCard data={data} />);
    expect(screen.getByText("1 part")).toBeInTheDocument();
  });
});
