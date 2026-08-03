import type { DeltaOutcome } from "../types";
import { instanceIdFromNode } from "./instanceIdFromNode";
import { FailureReason, ReasonDisclosure } from "./ReasonDisclosure";

// One row per parameter change inside the shared ChangesetCard (2026-07-04 widget redesign) — no
// longer its own bordered card (see ChangesetCard.tsx), just this section's rows: an icon, an
// old->after chip pair instead of plain text, the status badge, and reasoning one click away.

const COLORS: Record<string, string> = {
  APPLIED: "#3fb950",
  APPLIED_ADVISORY: "#d29922",  // applied outside the recommended range — copilot's judgment call
  REJECTED: "#f85149",
  CONFLICT: "#f85149",
};

function label(o: DeltaOutcome): string {
  if (o.status === "APPLIED_ADVISORY") return "APPLIED ⚠";
  return o.status;
}

// 2026-08-01 — plain provenance tag (packages/ledger/parameter.py::ParamSource), NOT a scoring/
// ranking system: just the label, verbatim, next to the value it describes. Absent or "unsourced"
// renders nothing, so this is invisible until a subsystem/delta actually sets a more specific value.
function sourceLabel(o: DeltaOutcome): string | null {
  if (!o.source || o.source === "unsourced") return null;
  return o.source.replace(/_/g, " ");
}

export function ProposalCard({
  outcomes,
  onUndo,
  undone,
  undoError,
  onHover,
}: {
  outcomes: DeltaOutcome[];
  onUndo: () => void;
  undone: boolean;
  undoError?: string;
  onHover?: (instanceId: string | null) => void;
}) {
  const undoable = outcomes.some((o) => o.oldValue != null && (o.status === "APPLIED" || o.status === "APPLIED_ADVISORY"));
  return (
    <div>
      {outcomes.map((o, i) => {
        const failed = o.status === "REJECTED" || o.status === "CONFLICT";
        const source = sourceLabel(o);
        return (
        <div key={i}
             onMouseEnter={() => onHover?.(instanceIdFromNode(o.node))}
             onMouseLeave={() => onHover?.(null)}>
          <div style={rowLine}>
            <span style={icon}>⇄</span>
            <span style={{ color: "#c9d1d9", flex: 1 }}>
              <b>{o.node.split(".").pop()}</b>{" "}
              <span style={chip}>{o.oldValue ?? "?"}</span>
              <span style={{ color: "#6e7681" }}> → </span>
              <span style={chip}>{o.applied ?? o.requested}</span>
              {source && (
                <span style={sourceTag} title="declared source of this value">{source}</span>
              )}
            </span>
            <span style={{ color: COLORS[o.status] ?? "#8b949e", fontWeight: 600, fontSize: 11 }}>
              {label(o)}
            </span>
            {failed ? <FailureReason reason={o.reason} /> : <ReasonDisclosure reason={o.reason} />}
          </div>
          {o.cascades && o.cascades.length > 0 && o.cascades.map((c, ci) => (
            <div key={ci} title={c.reason} style={cascadeLine}>
              <span>↳ <b>{c.node.split(".").pop()}</b> {c.old_value ?? "?"} → {c.value} <i>(cascaded)</i></span>
            </div>
          ))}
        </div>
        );
      })}
      {undoable && (
        <div style={{ marginTop: 6, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6 }}>
          {undoError && !undone && <FailureReason reason={undoError} />}
          <button onClick={onUndo} disabled={undone} style={{ ...undoBtn, opacity: undone ? 0.5 : 1 }}>
            {undone ? "↩ undone" : undoError ? "↩ retry Undo" : "↩ Undo"}
          </button>
        </div>
      )}
    </div>
  );
}

const rowLine: React.CSSProperties = {
  display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, padding: "3px 0", fontSize: 12,
};
const icon: React.CSSProperties = { color: "#8b949e", fontSize: 12, width: 14, textAlign: "center" };
const chip: React.CSSProperties = {
  background: "#161b22", border: "1px solid #30363d", borderRadius: 4, padding: "0 5px",
  color: "#8b949e", fontFamily: "monospace", fontSize: 11,
};
const sourceTag: React.CSSProperties = {
  marginLeft: 6, background: "#1c2128", border: "1px solid #30363d", borderRadius: 10,
  padding: "0 6px", color: "#8b949e", fontSize: 9, textTransform: "uppercase", letterSpacing: 0.3,
};
const cascadeLine: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  padding: "1px 0 1px 20px", fontSize: 11, color: "#8b949e",
};
const undoBtn: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "3px 10px", cursor: "pointer", fontSize: 11,
};
