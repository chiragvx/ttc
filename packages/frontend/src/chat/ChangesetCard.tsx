import type { ReactNode } from "react";

// One bordered container per turn instead of up to three separately-padded stacked cards (2026-07-04
// widget redesign) — a turn that proposes deltas AND feature_ops AND instance_ops together (e.g.
// "design a satellite") used to render three disconnected boxes; this groups them under one roof
// with a small label per section, so a turn with a lot to show doesn't fragment visually. A
// single-section message (the common case) just shows that one section, no label, no divider.
export function ChangesetCard({ sections }: { sections: { label: string; content: ReactNode }[] }) {
  const visible = sections.filter((s) => s.content);
  if (visible.length === 0) return null;
  return (
    <div style={card}>
      {visible.map((s, i) => (
        <div key={s.label} style={i > 0 ? sectionDivider : undefined}>
          {visible.length > 1 && <div style={sectionLabel}>{s.label}</div>}
          {s.content}
        </div>
      ))}
    </div>
  );
}

const card: React.CSSProperties = {
  marginTop: 8, padding: "8px 10px", border: "1px solid #30363d", borderRadius: 8, background: "#0d1117",
};
const sectionDivider: React.CSSProperties = { marginTop: 8, paddingTop: 8, borderTop: "1px solid #21262d" };
const sectionLabel: React.CSSProperties = {
  fontSize: 10, color: "#6e7681", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2,
};
