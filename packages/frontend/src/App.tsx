import { useState } from "react";
import { Chat } from "./Chat";
import { Controls } from "./Controls";
import { Hud } from "./Hud";
import { Settings, loadSettings, type LlmSettings } from "./Settings";
import { Viewport } from "./Viewport";
import { useCadSocket } from "./useCadSocket";
import { SKIN, type ParameterDelta } from "./types";

// Three-zone layout: intent + controls + settings sidebar | 3D viewport | telemetry floor rail.
export default function App() {
  const { connected, telemetry, lastReject, send } = useCadSocket();
  const [skin, setSkin] = useState(2);
  const [settings, setSettings] = useState<LlmSettings>(() => loadSettings());

  // Chat-proposed deltas are applied through the SAME rules-validated WS path as the sliders.
  const applyDeltas = (deltas: ParameterDelta[]) => {
    for (const d of deltas) {
      if (d.target_node === SKIN) setSkin(d.requested_value);
      send({ target_node: d.target_node, requested_value: d.requested_value, set_lock: d.set_lock ?? null });
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr auto", height: "100%" }}>
      <header style={{ display: "flex", justifyContent: "space-between", padding: "8px 16px", borderBottom: "1px solid #30363d", background: "#161b22" }}>
        <strong>Grounded Text-to-CAD</strong>
        <span style={{ fontSize: 12, color: connected ? "#3fb950" : "#f85149" }}>
          {connected ? "● connected" : "● offline"}
        </span>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", minHeight: 0 }}>
        <aside style={{ padding: 16, borderRight: "1px solid #30363d", overflowY: "auto", display: "flex", flexDirection: "column", gap: 20 }}>
          <Chat settings={settings} onApply={applyDeltas} />
          <Controls send={send} onSkin={setSkin} />
          <Settings value={settings} onChange={setSettings} />
          <p style={{ fontSize: 11, color: "#8b949e", margin: 0 }}>
            Intent and sliders both go through the backend rules validator: out-of-bounds → clamped;
            HARD_LOCK / forbidden node → a NACK on the floor rail. Export stays blocked until a grounded FS + sign-off.
          </p>
        </aside>
        <main style={{ minHeight: 0 }}>
          <Viewport skinMm={skin} />
        </main>
      </div>

      <Hud telemetry={telemetry} reject={lastReject} />
    </div>
  );
}
