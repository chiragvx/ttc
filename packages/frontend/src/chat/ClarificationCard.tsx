export function ClarificationCard({
  suggestions,
  onPick,
}: {
  suggestions: string[];
  onPick: (s: string) => void;
}) {
  if (!suggestions.length) return null;
  return (
    <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
      {suggestions.map((s, i) => (
        <button key={i} onClick={() => onPick(s)} style={chip}>
          {s}
        </button>
      ))}
    </div>
  );
}

const chip: React.CSSProperties = {
  background: "#161b22", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 14,
  padding: "4px 12px", cursor: "pointer", fontSize: 12,
};
