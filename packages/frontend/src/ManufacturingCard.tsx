import type { ManufacturingManifest } from "./types";

// A read-only make-manifest widget (Phase 6). Mirrors RequirementsCard.tsx's read-only,
// periodically-refetched summary card pattern exactly: material/process are never derived
// client-side — they, and the assembly step order (derived from the connection graph), come
// straight from GET /manufacturing/manifest. No editing/mutation lives here.
export function ManufacturingCard({
  data, bare,
}: {
  data: ManufacturingManifest | null;
  // when embedded inside another card/section that already provides its own border/background
  // (see ModelPanel.tsx), skip this component's own outer box so it doesn't double up
  bare?: boolean;
}) {
  // second-hop optional chaining (2026-07-19 review) — `data` can be truthy-but-malformed (e.g. an
  // error body that slipped past a non-2xx fetch response), so `.parts` itself isn't guaranteed
  const hasParts = !!data?.parts?.length;

  return (
    <div style={bare ? undefined : card}>
      {!bare && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: hasParts ? 8 : 0 }}>
          <strong style={{ fontSize: 13 }}>Manufacturing manifest</strong>
          {hasParts && (
            <span style={{ fontSize: 12, color: "#8b949e" }}>{data!.parts.length} part{data!.parts.length === 1 ? "" : "s"}</span>
          )}
        </div>
      )}
      {bare && hasParts && (
        <div style={{ fontSize: 12, color: "#8b949e", marginBottom: 8 }}>{data!.parts.length} part{data!.parts.length === 1 ? "" : "s"}</div>
      )}

      {!hasParts ? (
        <div style={{ fontSize: 11, color: "#8b949e" }}>
          No manufacturing manifest yet — add a part to see its material/process and assembly steps.
        </div>
      ) : (
        <>
          <div style={{ fontSize: 12, color: "#c9d1d9", marginBottom: 8 }}>
            Material: <b>{data!.material}</b>
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 4 }}>
            {data!.parts.map((p) => (
              <li key={p.instance_id} style={{ display: "flex", gap: 8, fontSize: 12, alignItems: "baseline" }}>
                <span style={{ flex: 1, color: "#c9d1d9" }}>{p.subsystem_type}</span>
                <span style={{ color: "#8b949e" }}>{p.material}</span>
                <span style={{ color: "#8b949e", fontVariantNumeric: "tabular-nums" }}>{p.process}</span>
              </li>
            ))}
          </ul>
          {!!data!.assembly_steps?.length && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 4 }}>Assembly steps</div>
              <ol style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 2 }}>
                {data!.assembly_steps.map((s, i) => (
                  <li key={i} style={{ fontSize: 12, color: "#c9d1d9" }}>{s}</li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const card: React.CSSProperties = { padding: "12px 14px", border: "1px solid #30363d", borderRadius: 10, background: "#161b22", marginBottom: 12 };
