import { useState } from "react";
import { Controls } from "./Controls";
import { Hud } from "./Hud";
import { Viewport } from "./Viewport";
import { useCadSocket } from "./useCadSocket";

// Three-zone layout: conversation/controls sidebar | 3D viewport | telemetry floor rail.
export default function App() {
  const { connected, telemetry, lastReject, send } = useCadSocket();
  const [skin, setSkin] = useState(2);

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr auto", height: "100%" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          padding: "8px 16px",
          borderBottom: "1px solid #30363d",
          background: "#161b22",
        }}
      >
        <strong>Grounded Text-to-CAD</strong>
        <span style={{ fontSize: 12, color: connected ? "#3fb950" : "#f85149" }}>
          {connected ? "● connected" : "● offline"}
        </span>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", minHeight: 0 }}>
        <aside style={{ padding: 16, borderRight: "1px solid #30363d", overflowY: "auto" }}>
          <Controls send={send} onSkin={setSkin} />
          <p style={{ fontSize: 11, color: "#8b949e", marginTop: 24 }}>
            Sliders are physically bounded by the backend rules validator. Out-of-bounds → clamped;
            a HARD_LOCK or forbidden node → a NACK shown on the floor rail.
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
