import { useState } from "react";
import type { InstanceRow, ParamSpec, SubsystemInfo } from "./api";
import { partLabel } from "./partLabel";

// The "Details" strip for whichever part is selected in the Outliner (2026-07-04) — replaces a bare
// "✕" with an actual sense of what a part IS and what removing it would do, per the redesign: plain
// description, live dimensions, feature count, dependents, and a click-to-reveal remove confirm
// instead of a blocking modal (every op has Undo now, per Phase 0 — reversibility over prediction).
export function PartDetail({
  instance,
  instances,
  subsystems,
  specs,
  values,
  onRemove,
}: {
  instance: InstanceRow | null;
  instances: InstanceRow[];
  subsystems: SubsystemInfo[];
  specs: ParamSpec[];
  values: Record<string, number>;
  onRemove: (id: string) => void;
  }) {
  const [confirming, setConfirming] = useState(false);

  if (!instance) return null;

  const info = subsystems.find((s) => s.name === instance.subsystem_type);
  const dims = specs.filter((s) => s.unit === "mm");
  const children = instances.filter((i) => i.parent_id === instance.id);

  return (
    <div style={panel}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <strong style={{ fontSize: 13 }}>{partLabel(instance, instances)}</strong>
        <span title={instance.id} style={{ fontSize: 10, color: "#6e7681" }}>({instance.id})</span>
      </div>
      {info?.description && (
        <div style={{ fontSize: 11, color: "#8b949e", marginTop: 3 }}>{info.description}</div>
      )}
      {dims.length > 0 && (
        <div style={{ fontSize: 11, color: "#c9d1d9", marginTop: 6, display: "flex", flexWrap: "wrap", gap: "4px 10px" }}>
          {dims.map((s) => (
            <span key={s.node}>{s.label}: {values[s.node] ?? s.value}{s.unit}</span>
          ))}
        </div>
      )}
      <div style={{ fontSize: 11, color: "#8b949e", marginTop: 6 }}>
        {instance.cut_feature_count === 0 ? "No cut features yet"
          : `${instance.cut_feature_count} cut feature${instance.cut_feature_count === 1 ? "" : "s"}`}
      </div>
      <div style={{ fontSize: 11, color: "#8b949e", marginTop: 2 }}>
        Depended on by: {children.length === 0 ? "none" : children.map((c) => partLabel(c, instances)).join(", ")}
      </div>

      <div style={{ marginTop: 8 }}>
        {children.length > 0 ? (
          <div style={note}>Has {children.length} child part{children.length === 1 ? "" : "s"} — remove them first.</div>
        ) : confirming ? (
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
            <span style={{ color: "#8b949e" }}>
              Remove {partLabel(instance, instances)}
              {instance.cut_feature_count > 0 ? ` and its ${instance.cut_feature_count} cut feature${instance.cut_feature_count === 1 ? "" : "s"}` : ""}?
            </span>
            <button onClick={() => { onRemove(instance.id); setConfirming(false); }} style={dangerBtn}>Remove</button>
            <button onClick={() => setConfirming(false)} style={btn}>Cancel</button>
          </div>
        ) : (
          <button onClick={() => setConfirming(true)} style={btn}>Remove this part</button>
        )}
      </div>
    </div>
  );
}

const panel: React.CSSProperties = {
  marginTop: 8, padding: 10, border: "1px solid #30363d", borderRadius: 8, background: "#0d1117",
};
const note: React.CSSProperties = { fontSize: 11, color: "#8b949e", fontStyle: "italic" };
const btn: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "3px 10px", cursor: "pointer", fontSize: 11,
};
const dangerBtn: React.CSSProperties = { ...btn, background: "#3a1618", border: "1px solid #f85149", color: "#ffb4ab" };
