import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Message } from "./Message";
import type { ChatMessage } from "../types";

// 2026-08-04 regression: a live SSE stream patches `msg.text` on EVERY token (thousands of tiny
// appends for a long response) — ReactMarkdown/remark-gfm re-parse their ENTIRE input on every
// render, so feeding the growing string through it on every token is O(n^2) over the response
// length and hung an actual browser tab on a long response. While `streaming` is true, the text
// must render as plain text (cheap, no parsing); the real Markdown parse happens exactly once,
// after the stream completes.

function assistantMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return { id: "a1", role: "assistant", text: "", ...overrides };
}

describe("Message", () => {
  it("renders growing streamed text as PLAIN text, not through Markdown, while streaming is true", () => {
    const { container } = render(
      <Message msg={assistantMsg({ text: "**bold** should stay literal mid-stream", streaming: true })} />,
    );
    // no markdown parsing happened: no <strong> element, the raw markdown syntax is visible as text
    expect(container.querySelector("strong")).toBeNull();
    expect(screen.getByText(/\*\*bold\*\* should stay literal mid-stream/)).toBeInTheDocument();
  });

  it("renders through Markdown exactly once the stream has finished (streaming: false)", () => {
    const { container } = render(
      <Message msg={assistantMsg({ text: "**bold** once done", streaming: false })} />,
    );
    const strong = container.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong?.textContent).toBe("bold");
  });

  it("renders through Markdown when streaming is entirely absent (non-streamed message)", () => {
    const { container } = render(<Message msg={assistantMsg({ text: "**bold**" })} />);
    expect(container.querySelector("strong")).not.toBeNull();
  });

  it("still shows the typing indicator while streaming with no text yet", () => {
    render(<Message msg={assistantMsg({ text: "", streaming: true })} />);
    expect(screen.getByLabelText("thinking")).toBeInTheDocument();
  });
});
