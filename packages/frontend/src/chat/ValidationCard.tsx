import type { ValidationResult } from "../types";

// Self-check result shown after a turn changed geometry (2026-07-19). Green when the design is sound;
// otherwise lists what the geometric (and, if a vision model is configured, visual) check found. When
// an LLM key is set the copilot auto-corrects from these findings; the card makes the loop visible.
const SEV_COLOR: Record<string, string> = { error: "#f85149", warning: "#d29922", info: "#58a6ff" };

export function ValidationCard({ result }: { result: ValidationResult }) {
  const issues = [
    ...result.geometric.issues,
    ...(result.visual ? result.visual.issues : []),
  ];
  const passed = result.ok && issues.length === 0;

  return (
    <div style={box}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: issues.length ? 6 : 0 }}>
        <span style={{ color: passed ? "#3fb950" : "#d29922", fontWeight: 600, fontSize: 12 }}>
          {passed ? "✓ Self-check passed" : "⚠ Self-check found issues"}
        </span>
        <span style={{ color: "#6e7681", fontSize: 10 }}>
          geometric{result.vision_ran ? " + visual" : result.vision_enabled ? " (visual skipped)" : ""}
        </span>
      </div>
      {issues.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 16 }}>
          {issues.map((i, k) => (
            <li key={k} style={{ fontSize: 11, color: "#c9d1d9", marginBottom: 2 }}>
              <span style={{ color: SEV_COLOR[i.severity] ?? "#8b949e", fontWeight: 600 }}>
                {i.check}
              </span>{" "}
              {i.message}
            </li>
          ))}
        </ul>
      )}
      {!result.vision_enabled && (
        <div style={{ fontSize: 10, color: "#6e7681", marginTop: 6, fontStyle: "italic" }}>
          Visual (blueprint) check is off — set a vision-capable model in Settings to enable the
          "does it look right" judgment.
        </div>
      )}
    </div>
  );
}

const box: React.CSSProperties = {
  border: "1px solid #30363d", borderRadius: 8, padding: "8px 10px", marginTop: 6,
  background: "#0d1117",
};
