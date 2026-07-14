import { useState } from "react";
import { DEFAULT_MODEL, clearKey, saveSettings, type LlmSettings } from "./settings";

export function SettingsModal({
  value,
  onChange,
  onClose,
}: {
  value: LlmSettings;
  onChange: (s: LlmSettings) => void;
  onClose: () => void;
}) {
  const [key, setKey] = useState(value.apiKey);
  const [model, setModel] = useState(value.model);
  const [authToken, setAuthToken] = useState(value.authToken);

  const save = () => {
    const s = { apiKey: key, model: model || DEFAULT_MODEL, authToken };
    saveSettings(s);
    onChange(s);
    onClose();
  };

  return (
    <div style={overlay} onClick={onClose}>
      <div style={modal} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: "0 0 12px" }}>LLM settings</h3>
        <label style={lbl}>OpenRouter API key</label>
        <input type="password" placeholder="sk-or-…" value={key} onChange={(e) => setKey(e.target.value)} style={input} />
        <label style={lbl}>Model</label>
        <input value={model} onChange={(e) => setModel(e.target.value)} style={input} />
        <label style={lbl}>Server auth token (only if the operator configured AUTH_TOKEN)</label>
        <input type="password" placeholder="leave blank if unset" value={authToken}
               onChange={(e) => setAuthToken(e.target.value)} style={input} />
        <p style={{ fontSize: 11, color: "#8b949e" }}>
          Stored only in your browser, sent per-request. Without a key <b>there is no LLM</b>.
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
          <button
            onClick={() => {
              setKey("");
              clearKey();
              onChange({ apiKey: "", model: model || DEFAULT_MODEL, authToken });
            }}
            style={btn}
          >
            Clear (no LLM)
          </button>
          <button onClick={save} style={{ ...btn, background: "#238636", borderColor: "#238636", color: "#fff" }}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

const overlay: React.CSSProperties = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", display: "grid", placeItems: "center", zIndex: 50,
};
const modal: React.CSSProperties = {
  width: 380, padding: 20, background: "#161b22", border: "1px solid #30363d", borderRadius: 12,
};
const input: React.CSSProperties = {
  width: "100%", padding: "7px 9px", marginTop: 4, marginBottom: 10, background: "#0d1117",
  border: "1px solid #30363d", borderRadius: 6, color: "#e6edf3", fontSize: 13,
};
const lbl: React.CSSProperties = { fontSize: 12, color: "#8b949e" };
const btn: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "7px 12px", cursor: "pointer", fontSize: 12,
};
