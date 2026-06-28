export type AnalysisStatus = "idle" | "running" | "optimizing" | "done" | "stale" | "error";

export interface AnalysisState {
  status: AnalysisStatus;
  fs: number | null;
  solverSeconds: number | null;
  exportStatus: string; // EXPORT_BLOCKED | EXPORT_ELIGIBLE
}

export function AnalysisBar({
  state,
  onAnalyze,
  onOptimize,
  onSignExport,
}: {
  state: AnalysisState;
  onAnalyze: () => void;
  onOptimize: () => void;
  onSignExport: () => void;
}) {
  const eligible = state.exportStatus === "EXPORT_ELIGIBLE";
  const fsColor = state.fs == null ? "#8b949e" : state.fs >= 1.5 ? "#3fb950" : "#f85149";
  const busy = state.status === "running" || state.status === "optimizing";
  return (
    <div style={row}>
      <button onClick={onAnalyze} disabled={busy} style={btn}>
        {state.status === "running" ? "Analyzing…" : "Run analysis"}
      </button>
      <button onClick={onOptimize} disabled={busy} style={btn} title="Find the lightest design that passes FS">
        {state.status === "optimizing" ? "Optimizing…" : "Optimize ⚙"}
      </button>
      {state.fs != null && (
        <span style={{ color: "#8b949e" }}>
          FS <b style={{ color: fsColor }}>{state.fs.toFixed(2)}</b>
          {state.solverSeconds != null && <span style={{ color: "#8b949e" }}> · {state.solverSeconds}s</span>}
        </span>
      )}
      {state.status === "stale" && <span style={{ color: "#d29922" }}>parameters changed — re-run analysis</span>}
      {state.status === "error" && <span style={{ color: "#f85149" }}>analysis failed</span>}
      <span style={{ flex: 1 }} />
      <span style={{ color: eligible ? "#3fb950" : "#8b949e" }}>
        Export: <b>{eligible ? "ELIGIBLE" : "blocked"}</b>
      </span>
      {eligible && (
        <button onClick={onSignExport} style={primaryBtn}>
          Sign off &amp; Export STEP
        </button>
      )}
    </div>
  );
}

const row: React.CSSProperties = {
  display: "flex", gap: 14, alignItems: "center", padding: "8px 16px",
  borderTop: "1px solid #30363d", background: "#0d1117", fontSize: 13,
};
const btn: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "6px 12px", cursor: "pointer", fontSize: 13,
};
const primaryBtn: React.CSSProperties = {
  background: "#238636", border: "none", color: "#fff", borderRadius: 6,
  padding: "6px 12px", cursor: "pointer", fontSize: 13,
};
