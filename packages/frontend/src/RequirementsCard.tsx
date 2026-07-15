import type { RequirementsData } from "./api";

// A read-only compliance widget. The GOAL is stated in the chat (the single input) — this panel just
// shows each requirement judged against the LIVE metric. factor_of_safety is "?" (unknown) until a
// real solver verdict exists — never assumed green.
const MARK: Record<string, { icon: string; color: string }> = {
  SATISFIED: { icon: "✓", color: "#3fb950" },
  VIOLATED: { icon: "✗", color: "#f85149" },
  UNKNOWN: { icon: "?", color: "#d29922" },
};

export function RequirementsCard({
  data, onOptimize, bare,
}: {
  data: RequirementsData | null;
  onOptimize: () => void;
  // when embedded inside another card/section that already provides its own border/background
  // (see ModelPanel.tsx), skip this component's own outer box so it doesn't double up
  bare?: boolean;
}) {
  const fsUnmet = data?.requirements.some((r) => r.metric === "factor_of_safety" && r.status !== "SATISFIED");

  return (
    <div style={bare ? undefined : card}>
      {!bare && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: data?.goal_set ? 8 : 0 }}>
          <strong style={{ fontSize: 13 }}>Goal &amp; compliance</strong>
          {data?.goal_set && (
            <span style={{ fontSize: 12, color: "#8b949e" }}>{data.satisfied}/{data.total} met</span>
          )}
        </div>
      )}
      {bare && data?.goal_set && (
        <div style={{ fontSize: 12, color: "#8b949e", marginBottom: 8 }}>{data.satisfied}/{data.total} met</div>
      )}

      {!data?.goal_set ? (
        <div style={{ fontSize: 11, color: "#8b949e" }}>
          State a goal in chat — e.g. <i>“a bracket that holds 200&nbsp;N at FS&nbsp;2, under 200&nbsp;g”</i>.
        </div>
      ) : (
        <>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 4 }}>
            {data.requirements.map((r) => {
              const m = MARK[r.status];
              return (
                <li key={r.id} style={{ display: "flex", gap: 8, fontSize: 12, alignItems: "baseline" }}>
                  <span style={{ color: m.color, fontWeight: 700, width: 12 }}>{m.icon}</span>
                  <span style={{ flex: 1, color: "#c9d1d9" }}>{r.text}</span>
                  <span style={{ color: m.color, fontVariantNumeric: "tabular-nums" }}>
                    {r.value == null ? "—" : r.metric === "print_time_s" ? `${Math.round(r.value)} s` : r.value}
                  </span>
                </li>
              );
            })}
          </ul>
          {data.implied_fs_floor != null && (
            <div style={{ fontSize: 11, color: "#8b949e", marginTop: 8 }}>
              Goal demands FS ≥ {data.implied_fs_floor}; the export gate now enforces FS ≥ {data.enforced_fs_floor}.
            </div>
          )}
          {data.implied_load_n != null && (
            <div style={{ fontSize: 11, color: "#8b949e", marginTop: 4 }}>
              Analysis now runs against the stated {data.implied_load_n} N load.
            </div>
          )}
          {fsUnmet && (
            <button onClick={onOptimize} style={fixBtn}>
              Find the lightest design meeting FS ≥ {data.enforced_fs_floor}
            </button>
          )}
        </>
      )}
    </div>
  );
}

const card: React.CSSProperties = { padding: "12px 14px", border: "1px solid #30363d", borderRadius: 10, background: "#161b22", marginBottom: 12 };
const fixBtn: React.CSSProperties = { marginTop: 10, width: "100%", background: "#1f6feb", border: "none", borderRadius: 6, color: "white", padding: "6px 10px", fontSize: 12, cursor: "pointer" };
