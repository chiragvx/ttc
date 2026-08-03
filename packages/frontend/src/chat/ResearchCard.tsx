import type { ResearchFinding } from "../types";

// Reference research (2026-08-01) — shows what the copilot checked before decomposing a NEW compound
// design into catalog parts, so "which part types" is grounded in something before the proposal below
// this card streams in. Advisory only: never a dimensional/manufacturer source (see the disclaimer
// line, always rendered verbatim from the backend, never edited/summarized client-side).
export function ResearchCard({ finding }: { finding: ResearchFinding }) {
  return (
    <div style={box}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        <span style={{ color: "#58a6ff", fontWeight: 600, fontSize: 12 }}>
          🔎 Checked reference designs
        </span>
      </div>
      <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 4 }}>
        “{finding.query}”
      </div>
      <div style={{ fontSize: 11, color: "#c9d1d9", marginBottom: finding.suggested_subsystem_types.length ? 6 : 0 }}>
        {finding.summary}
      </div>
      {finding.suggested_subsystem_types.length > 0 && (
        <div style={{ fontSize: 11, color: "#c9d1d9", marginBottom: 6 }}>
          <span style={{ color: "#8b949e" }}>Possibly-relevant part types: </span>
          {finding.suggested_subsystem_types.join(", ")}
        </div>
      )}
      {finding.image_urls.length > 0 && (
        // Which visual direction the research is heading — the model only ever reads text
        // (suggested_subsystem_types/summary), but showing the actual images lets the USER judge
        // that for themselves. Not every provider populates this (DuckDuckGo never does — its image
        // endpoint needs a token this provider doesn't mint; Bing does), so this is often empty.
        <div style={imageGrid}>
          {finding.image_urls.map((url, k) => (
            // A non-empty alt is required for this to register as an accessible "img" role at all
            // (an empty alt marks it decorative/presentational, dropping it from the a11y tree).
            <img key={k} src={url} alt={`reference image for "${finding.query}"`} loading="lazy" style={thumb} />
          ))}
        </div>
      )}
      {finding.source_urls.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 16, marginBottom: 6 }}>
          {finding.source_urls.map((url, k) => (
            <li key={k} style={{ fontSize: 10 }}>
              <a href={url} target="_blank" rel="noreferrer" style={{ color: "#58a6ff" }}>{url}</a>
            </li>
          ))}
        </ul>
      )}
      <div style={{ fontSize: 10, color: "#6e7681", fontStyle: "italic" }}>
        {finding.disclaimer}
      </div>
    </div>
  );
}

const box: React.CSSProperties = {
  border: "1px solid #30363d", borderRadius: 8, padding: "8px 10px", marginTop: 6,
  background: "#0d1117",
};

const imageGrid: React.CSSProperties = {
  display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6,
};

const thumb: React.CSSProperties = {
  width: 72, height: 72, objectFit: "cover", borderRadius: 4, border: "1px solid #30363d",
};
