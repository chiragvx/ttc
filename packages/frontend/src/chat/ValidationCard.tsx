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
  // Structural (2026-07-27) is deliberately kept OUT of the pass/fail banner above and out of
  // shouldAutoCorrect/buildCorrectionMessage's retry loop -- it's a coarse, informational FS readout
  // (a real number the moment a load is wired), not a defect to auto-fix. A part with a perfectly
  // fine estimated FS must not flip "Self-check passed" to "found issues" just for existing.
  const structuralIssues = result.structural.issues;

  return (
    <div style={box}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: issues.length ? 6 : 0 }}>
        <span style={{ color: passed ? "#3fb950" : "#d29922", fontWeight: 600, fontSize: 12 }}>
          {passed ? "✓ Self-check passed" : "⚠ Self-check found issues"}
        </span>
        <span
          style={{ color: "#6e7681", fontSize: 10 }}
          title={
            !result.vision_ran && result.vision_enabled
              ? "A vision check was attempted but came back inconclusive (the model may not support " +
                "image input, or the reply couldn't be parsed) — the geometric check above is unaffected."
              : undefined
          }
        >
          geometric{result.vision_ran ? " + visual" : result.vision_enabled ? " (visual inconclusive)" : ""}
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
      {structuralIssues.length > 0 && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid #21262d" }}>
          <div style={{ fontSize: 10, color: "#6e7681", marginBottom: 2 }}>
            Structural (coarse estimate — not a grounded verdict; run analysis for the real FS)
          </div>
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {structuralIssues.map((i, k) => (
              <li key={k} style={{ fontSize: 11, color: "#c9d1d9", marginBottom: 2 }}>
                <span style={{ color: SEV_COLOR[i.severity] ?? "#8b949e", fontWeight: 600 }}>
                  {i.instances[0] ?? i.check}
                </span>{" "}
                {i.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!result.vision_enabled && (
        <div style={{ fontSize: 10, color: "#6e7681", marginTop: 6, fontStyle: "italic" }}>
          Visual (blueprint) check is off — set a model in Settings (the main Model field works if
          it's vision-capable, e.g. Qwen/Gemini/GPT-4o variants) to enable the "does it look right"
          judgment.
        </div>
      )}
    </div>
  );
}

const box: React.CSSProperties = {
  border: "1px solid #30363d", borderRadius: 8, padding: "8px 10px", marginTop: 6,
  background: "#0d1117",
};
