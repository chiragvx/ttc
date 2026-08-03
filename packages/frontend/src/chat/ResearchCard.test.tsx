import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResearchCard } from "./ResearchCard";
import type { ResearchFinding } from "../types";

function finding(overrides: Partial<ResearchFinding> = {}): ResearchFinding {
  return {
    query: "adjustable laptop stand",
    summary: "typical adjustable laptop stands use a riser/hinge mechanism and a platform, not a rigid table",
    suggested_subsystem_types: [],
    source_urls: [],
    image_urls: [],
    disclaimer: "Reference only — not a dimensional or manufacturer source.",
    ...overrides,
  };
}

describe("ResearchCard", () => {
  it("renders the query and summary", () => {
    render(<ResearchCard finding={finding()} />);
    expect(screen.getByText(/“adjustable laptop stand”/)).toBeInTheDocument();
    expect(screen.getByText(/riser\/hinge mechanism/)).toBeInTheDocument();
  });

  it("always renders the disclaimer verbatim", () => {
    render(<ResearchCard finding={finding()} />);
    expect(screen.getByText("Reference only — not a dimensional or manufacturer source.")).toBeInTheDocument();
  });

  it("renders suggested subsystem types when present", () => {
    render(<ResearchCard finding={finding({ suggested_subsystem_types: ["hinge", "flat_bar"] })} />);
    expect(screen.getByText(/hinge, flat_bar/)).toBeInTheDocument();
  });

  it("renders nothing for suggested part types when the list is empty", () => {
    render(<ResearchCard finding={finding()} />);
    expect(screen.queryByText(/Possibly-relevant part types/)).not.toBeInTheDocument();
  });

  it("renders source links when present", () => {
    render(<ResearchCard finding={finding({ source_urls: ["https://example.com/laptop-stand"] })} />);
    const link = screen.getByRole("link", { name: "https://example.com/laptop-stand" });
    expect(link).toHaveAttribute("href", "https://example.com/laptop-stand");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("renders no source list when there are no urls", () => {
    render(<ResearchCard finding={finding()} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders an image per url when image_urls is populated", () => {
    const urls = ["https://example.com/a.jpg", "https://example.com/b.jpg"];
    render(<ResearchCard finding={finding({ image_urls: urls })} />);
    const images = screen.getAllByRole("img");
    expect(images).toHaveLength(2);
    expect(images.map((img) => img.getAttribute("src"))).toEqual(urls);
  });

  it("renders no images when image_urls is empty (e.g. DuckDuckGo, which never populates it)", () => {
    render(<ResearchCard finding={finding()} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
