import type { ChatMessage } from "../types";

// Closes the model's feedback loop (2026-07-04) — without this, a turn that got REJECTED just
// vanishes from what the model can see on the NEXT turn (the conversation history sent back is
// prose-only), so it has no way to learn a proposed id/parent didn't resolve, or that a part it
// just added is now called "enclosure_1". Appended to the assistant's own history entry (not shown
// in the UI — the cards already show this) so the model sees exactly what happened to its own
// proposal before it proposes the next one.
export function summarizeOutcomes(m: ChatMessage): string | null {
  const parts: string[] = [];

  if (m.outcomes) {
    for (const o of m.outcomes) {
      const node = o.node.split(".").pop();
      let entry = `delta ${node}=${o.applied ?? o.requested} -> ${o.status}`;
      if (o.reason) entry += `: ${o.reason}`;
      parts.push(entry);
    }
  }
  if (m.featureOps) {
    m.featureOps.forEach((op, i) => {
      const outcome = m.featureOpOutcomes?.[i];
      if (!outcome) return;
      let entry = `${op.op} on ${op.instance_id} -> ${outcome.status}`;
      if (outcome.status === "APPLIED" && outcome.feature) entry += ` (feature_id=${outcome.feature.id})`;
      if (outcome.reason) entry += `: ${outcome.reason}`;
      parts.push(entry);
    });
  }
  if (m.instanceOps) {
    m.instanceOps.forEach((op, i) => {
      const outcome = m.instanceOpOutcomes?.[i];
      if (!outcome) return;
      let entry = `${op.op}${op.subsystem_type ? ` ${op.subsystem_type}` : ""} -> ${outcome.status}`;
      if (outcome.status === "APPLIED" && outcome.instanceId) entry += ` (instance_id=${outcome.instanceId})`;
      if (outcome.reason) entry += `: ${outcome.reason}`;
      parts.push(entry);
    });
  }

  return parts.length > 0 ? `[outcomes: ${parts.join("; ")}]` : null;
}
