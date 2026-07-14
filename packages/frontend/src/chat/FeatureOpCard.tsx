import type { FeatureOp, FeatureOpOutcome } from "../types";
import { FailureReason, ReasonDisclosure } from "./ReasonDisclosure";

// The FeatureOp analog of ProposalCard — data shape (op/shape/dia/length/width/depth/position)
// doesn't map onto DeltaOutcome's node/oldValue/applied floats, so this is a sibling component
// rather than an overload of ProposalCard's rendering. Same COLORS convention. Auto-applied on
// receipt, same as deltas — Undo is only offered for add_feature/remove_feature (update_feature has
// no prior state to restore from). One row per proposal inside the shared ChangesetCard (no longer
// its own bordered card — see ChangesetCard.tsx).

const COLORS: Record<string, string> = {
  APPLIED: "#3fb950",
  REJECTED: "#f85149",
  CONFLICT: "#f85149",
};

// A shape glyph, not a verb — the icon says WHAT it cuts, the row text says where/how much.
function shapeIcon(op: FeatureOp): string {
  return op.shape === "rect" ? "▭" : "○";
}

function describe(op: FeatureOp): string {
  const kind = op.kind ?? "cut";
  if (op.op === "remove_feature") {
    return `remove ${kind} ${op.feature_id ?? "?"} on ${op.instance_id}`;
  }
  const verb = op.op === "add_feature" ? "add" : "update";
  const shapeDesc =
    op.shape === "circle" ? `${op.dia_mm ?? "?"}mm circle`
    : op.shape === "rect" ? `${op.length_mm ?? "?"}x${op.width_mm ?? "?"}mm rect`
    : "cut";
  const depthDesc = op.through ? "through" : op.depth_mm != null ? `${op.depth_mm}mm deep` : null;
  return `${verb} ${kind}: ${shapeDesc} on ${op.instance_id}${depthDesc ? `, ${depthDesc}` : ""}`;
}

export function FeatureOpCard({
  ops,
  outcomes,
  undone,
  undoError,
  onUndo,
  onHover,
}: {
  ops: FeatureOp[];
  outcomes: (FeatureOpOutcome | undefined)[];
  undone: Record<number, boolean>;
  undoError?: Record<number, string | undefined>;
  onUndo: (index: number) => void;
  onHover?: (instanceId: string | null) => void;
}) {
  return (
    <div>
      {ops.map((op, i) => {
        const outcome = outcomes[i];
        const canUndo = outcome?.status === "APPLIED" && (op.op === "add_feature" || op.op === "remove_feature");
        const failure = undoError?.[i];
        const opFailed = outcome?.status === "REJECTED" || outcome?.status === "CONFLICT";
        return (
          <div key={i} style={rowLine}
               onMouseEnter={() => onHover?.(op.instance_id)} onMouseLeave={() => onHover?.(null)}>
            <span style={icon}>{shapeIcon(op)}</span>
            <span style={{ color: "#c9d1d9", flex: 1 }}>{describe(op)}</span>
            {outcome ? (
              <span style={{ color: COLORS[outcome.status] ?? "#8b949e", fontWeight: 600, fontSize: 11 }}>
                {outcome.status}
              </span>
            ) : (
              // a large batch applies sequentially — this is what tells the user a queued op is
              // actively being worked, not stalled (2026-07-04, see Chat.tsx's incremental patching)
              <span style={{ color: "#6e7681", fontSize: 11, fontStyle: "italic" }}>applying…</span>
            )}
            {opFailed ? <FailureReason reason={outcome?.reason} /> : <ReasonDisclosure reason={outcome?.reason} />}
            {canUndo && (
              <button onClick={() => onUndo(i)} disabled={!!undone[i]} style={{ ...undoBtn, opacity: undone[i] ? 0.5 : 1 }}>
                {undone[i] ? "↩ undone" : "↩ Undo"}
              </button>
            )}
            {failure && <span style={undoFailNote}>Undo failed: {failure}</span>}
          </div>
        );
      })}
    </div>
  );
}

const rowLine: React.CSSProperties = {
  display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, padding: "3px 0", fontSize: 12,
};
const icon: React.CSSProperties = { color: "#8b949e", fontSize: 12, width: 14, textAlign: "center" };
const undoBtn: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "3px 10px", cursor: "pointer", fontSize: 11,
};
const undoFailNote: React.CSSProperties = { flexBasis: "100%", fontSize: 11, color: "#f85149", paddingLeft: 22 };
