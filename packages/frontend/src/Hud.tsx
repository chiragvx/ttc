import type { MutationRejected, TelemetryDelta } from "./types";

// Floor-rail telemetry HUD + the NACK surface (a rejected mutation is shown, never silently dropped).
export function Hud({ telemetry, reject }: { telemetry: TelemetryDelta | null; reject: MutationRejected | null }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 28,
        alignItems: "center",
        padding: "10px 16px",
        borderTop: "1px solid #30363d",
        fontSize: 13,
        background: "#161b22",
      }}
    >
      <Metric label="Mass" value={telemetry ? `${telemetry.total_mass_g.toFixed(1)} g` : "—"} />
      <Metric
        label="CG"
        value={telemetry ? `(${telemetry.cg_mm.map((v) => v.toFixed(0)).join(", ")}) mm` : "—"}
      />
      <Metric
        label="Print (est.)"
        value={telemetry ? `${(telemetry.estimated_print_time_s / 60).toFixed(0)} min` : "—"}
      />
      <Metric
        label="Cost (est.)"
        value={telemetry ? `$${telemetry.estimated_cost_usd.toFixed(2)}` : "—"}
      />
      <span style={{ flex: 1 }} />
      {reject && (
        <span style={{ color: "#f85149" }}>
          ⛔ {reject.status}: {reject.reason}
        </span>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <span style={{ color: "#8b949e" }}>{label}: </span>
      <b>{value}</b>
    </span>
  );
}
