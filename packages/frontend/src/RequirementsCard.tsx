import { useState } from "react";
import type { RequirementsData } from "./api";

// The design goal + a grounded compliance readout: each requirement judged against the LIVE metric.
// factor_of_safety is "?" (unknown) until a real solver verdict exists — never assumed green.
const MARK: Record<string, { icon: string; color: string }> = {
  SATISFIED: { icon: "✓", color: "#3fb950" },
  VIOLATED: { icon: "✗", color: "#f85149" },
  UNKNOWN: { icon: "?", color: "#d29922" },
};

export function RequirementsCard({
  data, onSetGoal, onOptimize,
}: {
  data: RequirementsData | null;
  onSetGoal: (goal: string) => void;
  onOptimize: () => void;
}) {
  const [goal, setGoal] = useState("");
  const fsUnmet = data?.requirements.some((r) => r.metric === "factor_of_safety" && r.status !== "SATISFIED");

  return (
    <div style={card}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <strong style={{ fontSize: 13 }}>Design goal</strong>
        {data?.goal_set && (
          <span style={{ fontSize: 12, color: "#8b949e" }}>
            {data.satisfied}/{data.total} met
          </span>
        )}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); if (goal.trim()) onSetGoal(goal.trim()); }}
        style={{ display: "flex", gap: 6, marginBottom: data?.goal_set ? 10 : 0 }}
      >
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="e.g. hold 200 N at FS 2, under 30 g"
          style={input}
        />
        <button type="submit" style={btn}>Set</button>
      </form>

      {data?.goal_set && (
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
const input: React.CSSProperties = { flex: 1, background: "#0d1117", border: "1px solid #30363d", borderRadius: 6, color: "#c9d1d9", padding: "5px 8px", fontSize: 12 };
const btn: React.CSSProperties = { background: "#238636", border: "none", borderRadius: 6, color: "white", padding: "5px 12px", fontSize: 12, cursor: "pointer" };
const fixBtn: React.CSSProperties = { marginTop: 10, width: "100%", background: "#1f6feb", border: "none", borderRadius: 6, color: "white", padding: "6px 10px", fontSize: 12, cursor: "pointer" };
