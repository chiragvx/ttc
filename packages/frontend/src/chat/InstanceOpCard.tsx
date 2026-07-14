import type { InstanceOp, InstanceOpOutcome } from "../types";
import { FailureReason, ReasonDisclosure } from "./ReasonDisclosure";

// The InstanceOp analog of FeatureOpCard: data shape (op/subsystem_type/instance_id/parent/position)
// doesn't map onto DeltaOutcome's node/oldValue/applied floats, so this is a sibling component
// rather than an overload of ProposalCard's rendering. Same COLORS convention. Auto-applied on
// receipt, same as deltas — Undo re-adds/removes the instance, or replays its exact prior transform
// for a move (see App.tsx::undoInstanceOp; add/remove are a practical re-add, never a literal undo —
// move_instance's Undo IS exact). One row per proposal inside the shared ChangesetCard.

const COLORS: Record<string, string> = {
  APPLIED: "#3fb950",
  REJECTED: "#f85149",
  CONFLICT: "#f85149",
};

function describe(op: InstanceOp): string {
  if (op.op === "remove_instance") {
    return `remove ${op.instance_id ?? "?"}`;
  }
  if (op.op === "move_instance") {
    const pos = op.x_mm != null && op.y_mm != null && op.z_mm != null
      ? ` to (${op.x_mm}, ${op.y_mm}, ${op.z_mm})` : "";
    return `move ${op.instance_id ?? "?"}${pos}`;
  }
  const named = op.instance_id ? ` (as '${op.instance_id}')` : "";
  return `add ${op.subsystem_type ?? "?"}${named}`;
}

// The instance this row concerns, for the viewport hover marker — the one about to be (or just was)
// removed, added, or moved; whichever the outcome/op actually names. move_instance never changes an
// id (the instance being repositioned keeps it), so the shared else-branch below — preferring the
// outcome's resolved id, falling back to the op's — already does the right thing for it unchanged.
function hoverTarget(op: InstanceOp, outcome?: InstanceOpOutcome): string | null {
  if (op.op === "remove_instance") return op.instance_id ?? outcome?.instanceId ?? null;
  return outcome?.instanceId ?? op.instance_id ?? null;
}

export function InstanceOpCard({
  ops,
  outcomes,
  undone,
  undoError,
  onUndo,
  onHover,
}: {
  ops: InstanceOp[];
  outcomes: (InstanceOpOutcome | undefined)[];
  undone: Record<number, boolean>;
  undoError?: Record<number, string | undefined>;
  onUndo: (index: number) => void;
  onHover?: (instanceId: string | null) => void;
}) {
  return (
    <div>
      {ops.map((op, i) => {
        const outcome = outcomes[i];
        const canUndo = outcome?.status === "APPLIED";
        const failure = undoError?.[i];
        const opFailed = outcome?.status === "REJECTED" || outcome?.status === "CONFLICT";
        return (
          <div key={i} style={rowLine}
               onMouseEnter={() => onHover?.(hoverTarget(op, outcome))} onMouseLeave={() => onHover?.(null)}>
            <span style={icon}>{op.op === "remove_instance" ? "−" : op.op === "move_instance" ? "→" : "+"}</span>
            <span style={{ color: "#c9d1d9", flex: 1 }}>{describe(op)}</span>
            {outcome ? (
              <span style={{ color: COLORS[outcome.status] ?? "#8b949e", fontWeight: 600, fontSize: 11 }}>
                {outcome.status}
              </span>
            ) : (
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
const icon: React.CSSProperties = { color: "#8b949e", fontSize: 13, width: 14, textAlign: "center", fontWeight: 700 };
const undoBtn: React.CSSProperties = {
  background: "#21262d", border: "1px solid #30363d", color: "#e6edf3", borderRadius: 6,
  padding: "3px 10px", cursor: "pointer", fontSize: 11,
};
const undoFailNote: React.CSSProperties = { flexBasis: "100%", fontSize: 11, color: "#f85149", paddingLeft: 22 };
