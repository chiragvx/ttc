import { HOLE_DIA, RIB, SKIN } from "./types";

interface Bound {
  node: string;
  label: string;
  min: number;
  max: number;
  step: number;
}

const BOUNDS: Bound[] = [
  { node: SKIN, label: "Skin thickness (mm)", min: 1, max: 5, step: 0.1 },
  { node: RIB, label: "Rib spacing (mm)", min: 10, max: 50, step: 1 },
  { node: HOLE_DIA, label: "Bolt-hole dia (mm)", min: 3, max: 10, step: 0.5 },
];

// Floating contextual parameter panel over the viewport (PRD style). Bounded sliders + HARD_LOCK.
export function FloatingControls({
  value,
  locked,
  onChange,
  onLock,
}: {
  value: Record<string, number>;
  locked: Record<string, boolean>;
  onChange: (node: string, v: number) => void;
  onLock: (node: string, locked: boolean) => void;
}) {
  return (
    <div style={panel}>
      <div style={{ fontSize: 10, color: "#8b949e", marginBottom: 10, textTransform: "uppercase", letterSpacing: 0.6 }}>
        Parameters
      </div>
      {BOUNDS.map((b) => (
        <div key={b.node} style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 2 }}>
            <span style={{ color: "#c9d1d9" }}>{b.label}</span>
            <span>
              <b>{(value[b.node] ?? b.min).toFixed(1)}</b>
              <button onClick={() => onLock(b.node, !locked[b.node])} title="Hard-lock" style={lockBtn}>
                {locked[b.node] ? "🔒" : "🔓"}
              </button>
            </span>
          </div>
          <input
            type="range"
            min={b.min}
            max={b.max}
            step={b.step}
            value={value[b.node] ?? b.min}
            disabled={locked[b.node]}
            onChange={(e) => onChange(b.node, parseFloat(e.target.value))}
            style={{ width: "100%", accentColor: "#1f6feb" }}
          />
        </div>
      ))}
    </div>
  );
}

const panel: React.CSSProperties = {
  position: "absolute", top: 16, right: 16, width: 220, padding: 14, zIndex: 5,
  background: "rgba(22,27,34,0.92)", border: "1px solid #30363d", borderRadius: 10,
  boxShadow: "0 8px 24px rgba(0,0,0,0.45)", backdropFilter: "blur(6px)",
};
const lockBtn: React.CSSProperties = {
  marginLeft: 8, background: "none", border: "none", cursor: "pointer", fontSize: 13,
};
