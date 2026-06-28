import { useEffect, useRef, type ReactNode } from "react";
import { Message } from "./Message";
import type { ChatMessage } from "../types";

const EXAMPLES = ["Make the skin 3 mm", "What can I change?", "Make it lighter", "Set rib spacing to 25"];

export function MessageList({
  messages,
  renderExtras,
  onExample,
}: {
  messages: ChatMessage[];
  renderExtras: (m: ChatMessage) => ReactNode;
  onExample: (s: string) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (!messages.length) {
    return (
      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", justifyContent: "center", gap: 16, padding: "0 6px" }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>CAD copilot</div>
          <div style={{ fontSize: 13, color: "#8b949e", marginTop: 6, lineHeight: 1.5 }}>
            Describe what you want and I'll propose validated parameter changes. I never write geometry
            directly — every change is bounds-checked, and export stays blocked until a real
            factor-of-safety exists.
          </div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {EXAMPLES.map((e) => (
            <button key={e} onClick={() => onExample(e)} style={chip}>
              {e}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "0 6px" }}>
      {messages.map((m) => (
        <Message key={m.id} msg={m}>
          {renderExtras(m)}
        </Message>
      ))}
      <div ref={endRef} />
    </div>
  );
}

const chip: React.CSSProperties = {
  background: "#161b22", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 14,
  padding: "5px 12px", cursor: "pointer", fontSize: 12,
};
