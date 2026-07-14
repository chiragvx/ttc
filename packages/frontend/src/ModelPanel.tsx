import { useState } from "react";
import type { InstanceRow, ParamSpec, RequirementsData, SubsystemInfo } from "./api";
import { PartDetail } from "./PartDetail";
import { partLabel } from "./partLabel";
import { RequirementsCard } from "./RequirementsCard";

// Redesign (2026-07-04): the left sidebar is chat-only now — "Parts in this project" used to sit
// above the chat and, with a real design's worth of parts, could push the conversation down to a
// sliver with the input box nearly off-screen. Parts/Params/Goal all describe the CURRENT MODEL,
// not the conversation, so they move here: one floating panel over the viewport (where
// FloatingControls used to live alone), collapsible section by section, capped so it can never grow
// past the screen regardless of part count.
function Section({
  title, count, headerExtra, defaultOpen = true, children,
}: {
  title: string;
  count?: number;
  headerExtra?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={section}>
      <div style={sectionHeader}>
        <button onClick={() => setOpen((v) => !v)} style={sectionToggle}>
          {open ? "▾" : "▸"} {title}{count != null ? ` (${count})` : ""}
        </button>
        {headerExtra}
      </div>
      {open && <div style={sectionBody}>{children}</div>}
    </div>
  );
}

export function ModelPanel({
  instances,
  subsystems,
  specs,
  values,
  locked,
  requirements,
  onSelect,
  onAdd,
  onRemove,
  onHover,
  onChange,
  onLock,
  onOptimize,
}: {
  instances: InstanceRow[];
  subsystems: SubsystemInfo[];
  specs: ParamSpec[];
  values: Record<string, number>;
  locked: Record<string, boolean>;
  requirements: RequirementsData | null;
  onSelect: (id: string) => void;
  onAdd: (subsystemType: string) => void;
  onRemove: (id: string) => void;
  onHover?: (id: string | null) => void;
  onChange: (node: string, v: number) => void;
  onLock: (node: string, locked: boolean) => void;
  onOptimize: () => void;
}) {
  const [picking, setPicking] = useState(false);
  const active = instances.find((i) => i.is_active) ?? null;

  return (
    <div style={panel}>
      <Section
        title="Parts"
        count={instances.length}
        headerExtra={
          <button onClick={() => setPicking((v) => !v)} title="Add another part" style={addBtn}>
            {picking ? "✕" : "+"}
          </button>
        }
      >
        {picking && (
          <div style={pickerBox}>
            {subsystems.map((s) => (
              <button
                key={s.name}
                onClick={() => { onAdd(s.name); setPicking(false); }}
                title={s.description}
                style={pickerItem}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}

        {instances.length === 0 && !picking && (
          <div style={{ fontSize: 11, color: "#6e7681", fontStyle: "italic", padding: "4px 2px" }}>
            No parts yet — tell the copilot what to build, or add one manually with "+".
          </div>
        )}

        {instances.length > 0 && (
          <div style={rowList}>
            {instances.map((inst) => (
              <div
                key={inst.id}
                onClick={() => !inst.is_active && onSelect(inst.id)}
                onMouseEnter={() => onHover?.(inst.id)}
                onMouseLeave={() => onHover?.(null)}
                style={{ ...row, background: inst.is_active ? "#1f6feb22" : "transparent",
                         borderColor: inst.is_active ? "#1f6feb" : "#30363d" }}
              >
                <span style={{ color: inst.is_active ? "#c9d1d9" : "#8b949e", fontSize: 12 }}>
                  ▫ {partLabel(inst, instances)}
                </span>
              </div>
            ))}
          </div>
        )}

        <PartDetail key={active?.id ?? "none"} instance={active} instances={instances}
                    subsystems={subsystems} specs={specs} values={values} onRemove={onRemove} />
      </Section>

      {specs.length > 0 && (
        <Section title="Parameters">
          {specs.map((b) => {
            const v = values[b.node] ?? b.value;
            const isLocked = locked[b.node] ?? b.locked;
            const outside = v < b.min || v > b.max;
            const headroom = Math.max(b.step, (b.max - b.min) * 0.1);
            const sliderMin = outside ? Math.min(b.min, v - headroom) : b.min;
            const sliderMax = outside ? Math.max(b.max, v + headroom) : b.max;
            return (
              <div key={b.node} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 2 }}>
                  <span style={{ color: "#c9d1d9" }}>{b.label} ({b.unit})</span>
                  <span>
                    <b style={{ color: outside ? "#d29922" : "#c9d1d9" }}>{v.toFixed(b.step < 1 ? 1 : 0)}</b>
                    {outside && <span title={`outside recommended [${b.min}, ${b.max}]`} style={{ color: "#d29922", marginLeft: 4 }}>⚠</span>}
                    <button onClick={() => onLock(b.node, !isLocked)} title="Hard-lock" style={lockBtn}>
                      {isLocked ? "🔒" : "🔓"}
                    </button>
                  </span>
                </div>
                <input
                  type="range"
                  min={sliderMin}
                  max={sliderMax}
                  step={b.step}
                  value={v}
                  disabled={isLocked}
                  onChange={(e) => onChange(b.node, parseFloat(e.target.value))}
                  style={{ width: "100%", accentColor: outside ? "#d29922" : "#1f6feb" }}
                />
              </div>
            );
          })}
        </Section>
      )}

      <Section title="Goal & compliance" defaultOpen={!!requirements?.goal_set}>
        <RequirementsCard data={requirements} onOptimize={onOptimize} bare />
      </Section>
    </div>
  );
}

const panel: React.CSSProperties = {
  // `bottom: 16` (not a `calc(100vh - ...)` max-height) so the browser sizes this against its real
  // containing block — <main>, which sits BELOW the header — instead of the raw viewport. A vh-based
  // calc has no idea how tall the header/footer are, so it consistently ran ~header-height past the
  // actual visible area, forcing the whole page to scroll and pushing the header out of view
  // (2026-07-04, reported live: "right side panel... making the navbar go out of bounds").
  position: "absolute", top: 16, right: 16, bottom: 16, width: 280,
  overflowY: "auto", zIndex: 5,
  background: "rgba(22,27,34,0.92)", border: "1px solid #30363d", borderRadius: 10,
  boxShadow: "0 8px 24px rgba(0,0,0,0.45)", backdropFilter: "blur(6px)",
};
const section: React.CSSProperties = { padding: "10px 14px", borderBottom: "1px solid #30363d" };
const sectionHeader: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "center" };
const sectionToggle: React.CSSProperties = {
  background: "none", border: "none", color: "#8b949e", cursor: "pointer", fontSize: 10,
  textTransform: "uppercase", letterSpacing: 0.6, padding: 0, textAlign: "left",
};
const sectionBody: React.CSSProperties = { marginTop: 8 };
const addBtn: React.CSSProperties = {
  background: "none", border: "1px solid #30363d", borderRadius: 6, color: "#8b949e",
  cursor: "pointer", fontSize: 12, padding: "1px 8px",
};
const pickerBox: React.CSSProperties = {
  display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8, padding: 6,
  border: "1px dashed #30363d", borderRadius: 6,
};
const pickerItem: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "2px 8px", cursor: "pointer", fontSize: 11,
};
const rowList: React.CSSProperties = { maxHeight: 220, overflowY: "auto", marginBottom: 4 };
const row: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  padding: "4px 8px", marginBottom: 4, border: "1px solid #30363d", borderRadius: 6, cursor: "pointer",
};
const lockBtn: React.CSSProperties = {
  marginLeft: 8, background: "none", border: "none", cursor: "pointer", fontSize: 13,
};
