import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TypingIndicator } from "./TypingIndicator";
import type { ChatMessage } from "../types";

export function Message({ msg, children }: { msg: ChatMessage; children?: ReactNode }) {
  const isUser = msg.role === "user";
  return (
    <div style={{ display: "flex", gap: 10, padding: "10px 2px" }}>
      <div
        style={{
          width: 26, height: 26, borderRadius: 6, flexShrink: 0, display: "grid", placeItems: "center",
          fontSize: 13, fontWeight: 700, background: isUser ? "#1f6feb" : "#6e40c9", color: "#fff",
        }}
      >
        {isUser ? "U" : "◆"}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 3 }}>{isUser ? "You" : "CAD copilot"}</div>
        {isUser ? (
          <div style={{ fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{msg.text}</div>
        ) : msg.text ? (
          <div className="md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
          </div>
        ) : msg.streaming ? (
          <TypingIndicator />
        ) : null}
        {children}
      </div>
    </div>
  );
}
