import type { PickableFeature } from "./types";

// Rough click-to-select groundwork (2026-07-03): a small card anchored near a clicked point in the
// viewport, showing whichever pickable feature (a generator-baked tag — a hole, a bore, a mount
// point) was nearest the click. NOT precise face-level picking — see packages/subsystems/features.py
// for the documented approximation. Screen-anchored via raw client X/Y from the click event.
export function FeatureCard({
  feature,
  screenX,
  screenY,
  onClose,
}: {
  feature: PickableFeature;
  screenX: number;
  screenY: number;
  onClose: () => void;
}) {
  const metaRows = Object.entries(feature.meta).filter(([k]) => k !== "kind");
  return (
    <div style={{ ...card, left: screenX + 12, top: screenY + 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <strong style={{ fontSize: 12, color: "#c9d1d9" }}>{feature.tag}</strong>
        <button onClick={onClose} style={closeBtn}>✕</button>
      </div>
      <div style={{ fontSize: 11, color: "#8b949e" }}>
        {String(feature.meta.kind ?? "feature")} on <b>{feature.instance_id}</b>
      </div>
      {metaRows.length > 0 && (
        <div style={{ marginTop: 4, fontSize: 11, color: "#8b949e" }}>
          {metaRows.map(([k, v]) => (
            <div key={k}>{k}: {Array.isArray(v) ? v.map((n) => Number(n).toFixed(1)).join(", ") : String(v)}</div>
          ))}
        </div>
      )}
    </div>
  );
}

const card: React.CSSProperties = {
  position: "fixed", zIndex: 10, minWidth: 140, maxWidth: 220, padding: "8px 10px",
  background: "rgba(22,27,34,0.97)", border: "1px solid #30363d", borderRadius: 8,
  boxShadow: "0 8px 24px rgba(0,0,0,0.45)", pointerEvents: "auto",
};
const closeBtn: React.CSSProperties = {
  background: "none", border: "none", color: "#8b949e", cursor: "pointer", fontSize: 12, padding: 0,
};
