import type { DeltaOutcome } from "../types";

const COLORS: Record<string, string> = {
  APPLIED: "#3fb950",
  CLAMPED: "#d29922",
  REJECTED: "#f85149",
  CONFLICT: "#f85149",
};

function label(o: DeltaOutcome): string {
  if (o.status === "CLAMPED") return `CLAMPED → ${o.applied}`;
  return o.status;
}

export function ProposalCard({
  outcomes,
  onUndo,
  undone,
}: {
  outcomes: DeltaOutcome[];
  onUndo: () => void;
  undone: boolean;
}) {
  const undoable = outcomes.some((o) => o.oldValue != null && (o.status === "APPLIED" || o.status === "CLAMPED"));
  return (
    <div style={card}>
      {outcomes.map((o, i) => (
        <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "3px 0", fontSize: 12 }}>
          <span style={{ color: "#c9d1d9" }}>
            <b>{o.node.split(".").pop()}</b>{" "}
            <span style={{ color: "#8b949e" }}>{o.oldValue ?? "?"} → {o.applied ?? o.requested}</span>
          </span>
          <span title={o.reason} style={{ color: COLORS[o.status] ?? "#8b949e", fontWeight: 600, fontSize: 11 }}>
            {label(o)}
          </span>
        </div>
      ))}
      {undoable && (
        <div style={{ marginTop: 6, display: "flex", justifyContent: "flex-end" }}>
          <button onClick={onUndo} disabled={undone} style={{ ...undoBtn, opacity: undone ? 0.5 : 1 }}>
            {undone ? "↩ undone" : "↩ Undo"}
          </button>
        </div>
      )}
    </div>
  );
}

const card: React.CSSProperties = {
  marginTop: 8, padding: "8px 10px", border: "1px solid #30363d", borderRadius: 8, background: "#0d1117",
};
const undoBtn: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "3px 10px", cursor: "pointer", fontSize: 11,
};
