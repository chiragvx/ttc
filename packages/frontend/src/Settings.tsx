import { useState } from "react";

export interface LlmSettings {
  apiKey: string;
  model: string;
}

const KEY = "openrouter_key";
const MODEL = "openrouter_model";
const DEFAULT_MODEL = "deepseek/deepseek-chat";

export function loadSettings(): LlmSettings {
  return {
    apiKey: localStorage.getItem(KEY) ?? "",
    model: localStorage.getItem(MODEL) ?? DEFAULT_MODEL,
  };
}

// Settings panel — the user pastes their own OpenRouter key (kept in localStorage, never committed).
export function Settings({ value, onChange }: { value: LlmSettings; onChange: (s: LlmSettings) => void }) {
  const [open, setOpen] = useState(false);
  const [draftKey, setDraftKey] = useState(value.apiKey);
  const [draftModel, setDraftModel] = useState(value.model);

  const save = () => {
    localStorage.setItem(KEY, draftKey);
    localStorage.setItem(MODEL, draftModel || DEFAULT_MODEL);
    onChange({ apiKey: draftKey, model: draftModel || DEFAULT_MODEL });
    setOpen(false);
  };

  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={() => setOpen((o) => !o)} style={btn}>
        ⚙ LLM settings {value.apiKey ? "· OpenRouter" : "· mock"}
      </button>
      {open && (
        <div style={{ marginTop: 8, padding: 12, border: "1px solid #30363d", borderRadius: 6, background: "#0d1117" }}>
          <label style={lbl}>OpenRouter API key</label>
          <input
            type="password"
            placeholder="sk-or-…"
            value={draftKey}
            onChange={(e) => setDraftKey(e.target.value)}
            style={input}
          />
          <label style={lbl}>Model</label>
          <input value={draftModel} onChange={(e) => setDraftModel(e.target.value)} style={input} />
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button onClick={save} style={{ ...btn, background: "#238636", borderColor: "#238636" }}>Save</button>
            <button
              onClick={() => {
                setDraftKey("");
                localStorage.removeItem(KEY);
                onChange({ apiKey: "", model: draftModel || DEFAULT_MODEL });
              }}
              style={btn}
            >
              Clear (use mock)
            </button>
          </div>
          <p style={{ fontSize: 11, color: "#8b949e", marginBottom: 0 }}>
            Stored only in your browser. Without a key, an offline mock provider answers.
          </p>
        </div>
      )}
    </div>
  );
}

const btn: React.CSSProperties = {
  background: "#21262d",
  border: "1px solid #30363d",
  color: "#e6edf3",
  borderRadius: 6,
  padding: "6px 10px",
  cursor: "pointer",
  fontSize: 12,
};
const input: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  marginTop: 4,
  marginBottom: 8,
  background: "#161b22",
  border: "1px solid #30363d",
  borderRadius: 6,
  color: "#e6edf3",
  fontSize: 12,
};
const lbl: React.CSSProperties = { fontSize: 12, color: "#8b949e" };
