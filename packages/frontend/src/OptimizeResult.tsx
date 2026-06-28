export interface OptimizeResultData {
  variants: { skin: number; fs: number | null; mass_g: number; feasible: boolean }[];
  bestSkin: number | null;
  bestMass: number | null;
}

export function OptimizeResult({ result, onClose }: { result: OptimizeResultData; onClose: () => void }) {
  return (
    <div style={panel}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <strong style={{ fontSize: 13 }}>Optimization — lightest passing design</strong>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "#8b949e", cursor: "pointer", fontSize: 14 }}>
          ✕
        </button>
      </div>
      <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ color: "#8b949e" }}>
            <th style={th}>skin</th>
            <th style={th}>FS</th>
            <th style={th}>mass</th>
            <th style={th}></th>
          </tr>
        </thead>
        <tbody>
          {result.variants.map((v, i) => {
            const chosen = v.skin === result.bestSkin;
            return (
              <tr key={i} style={{ color: chosen ? "#3fb950" : v.feasible ? "#c9d1d9" : "#8b949e" }}>
                <td style={td}>{v.skin} mm</td>
                <td style={td}>{v.fs?.toFixed(2) ?? "—"}</td>
                <td style={td}>{v.mass_g} g</td>
                <td style={td}>{chosen ? "✓ chosen" : v.feasible ? "passes" : "fails FS"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div style={{ fontSize: 12, color: "#8b949e", marginTop: 8 }}>
        {result.bestSkin != null ? (
          <>
            Chose the lightest design that meets the FS floor: <b style={{ color: "#3fb950" }}>{result.bestSkin} mm</b>{" "}
            ({result.bestMass} g) — applied to the model.
          </>
        ) : (
          "No candidate passes the FS floor — lower the load or change material."
        )}
      </div>
    </div>
  );
}

const panel: React.CSSProperties = {
  position: "absolute", left: 16, bottom: 16, width: 280, padding: 14, zIndex: 5,
  background: "rgba(22,27,34,0.95)", border: "1px solid #30363d", borderRadius: 10,
  boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
};
const th: React.CSSProperties = { textAlign: "left", fontWeight: 500, padding: "2px 6px" };
const td: React.CSSProperties = { padding: "3px 6px" };
