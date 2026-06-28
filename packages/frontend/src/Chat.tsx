import { useState } from "react";
import { postPropose } from "./api";
import type { LlmSettings } from "./Settings";
import type { ParameterDelta } from "./types";

interface Props {
  settings: LlmSettings;
  onApply: (deltas: ParameterDelta[]) => void;
}

interface LogLine {
  intent: string;
  reply: string;
  kind: "applied" | "clarify" | "error";
}

// Conversation deck: NL intent -> /propose -> (apply deltas | ask for clarification).
export function Chat({ settings, onApply }: Props) {
  const [intent, setIntent] = useState("");
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<LogLine[]>([]);

  const submit = async () => {
    const text = intent.trim();
    if (!text || busy) return;
    setBusy(true);
    setIntent("");
    try {
      const res = await postPropose(text, settings.apiKey, settings.model);
      if (res.no_llm) {
        setLog((l) => [...l, { intent: text, reply: "No LLM configured — add an OpenRouter API key in ⚙ settings.", kind: "error" }]);
      } else if (res.clarification) {
        setLog((l) => [...l, { intent: text, reply: res.clarification!, kind: "clarify" }]);
      } else if (res.deltas.length) {
        onApply(res.deltas);
        const summary = res.deltas
          .map((d) => `${d.target_node.split(".").pop()} → ${d.requested_value}`)
          .join(", ");
        setLog((l) => [...l, { intent: text, reply: `applied: ${summary} (${res.provider})`, kind: "applied" }]);
      } else {
        setLog((l) => [...l, { intent: text, reply: "no change proposed", kind: "clarify" }]);
      }
    } catch (e) {
      setLog((l) => [...l, { intent: text, reply: String(e), kind: "error" }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h3 style={{ margin: "0 0 2px" }}>Intent</h3>
      {!settings.apiKey && (
        <div style={{ fontSize: 11, color: "#d29922" }}>
          No LLM configured — add an OpenRouter key in ⚙ settings below to enable the chat.
        </div>
      )}
      <div style={{ display: "flex", gap: 6 }}>
        <input
          value={intent}
          placeholder='e.g. "make the skin 3 mm"'
          onChange={(e) => setIntent(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          style={{ flex: 1, padding: "6px 8px", background: "#161b22", border: "1px solid #30363d", borderRadius: 6, color: "#e6edf3", fontSize: 13 }}
        />
        <button onClick={submit} disabled={busy} style={{ background: "#1f6feb", border: "none", color: "#fff", borderRadius: 6, padding: "0 12px", cursor: "pointer" }}>
          {busy ? "…" : "Send"}
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
        {log.slice(-6).map((l, i) => (
          <div key={i} style={{ fontSize: 12 }}>
            <div style={{ color: "#8b949e" }}>› {l.intent}</div>
            <div style={{ color: l.kind === "applied" ? "#3fb950" : l.kind === "error" ? "#f85149" : "#d29922" }}>
              {l.kind === "clarify" ? "? " : l.kind === "error" ? "⚠ " : "✓ "}
              {l.reply}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
