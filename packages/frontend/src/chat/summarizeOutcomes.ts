import type { ChatMessage } from "../types";

// Closes the model's feedback loop (2026-07-04) — without this, a turn that got REJECTED just
// vanishes from what the model can see on the NEXT turn (the conversation history sent back is
// prose-only), so it has no way to learn a proposed id/parent didn't resolve, or that a part it
// just added is now called "enclosure_1". Appended to the assistant's own history entry (not shown
// in the UI — the cards already show this) so the model sees exactly what happened to its own
// proposal before it proposes the next one.
// 2026-08-05: a remove_instance/remove_connection can cascade-delete connections/couplings/regions/
// fit_bindings/join_annotations that referenced the removed id (those ids get REUSED, so a stale
// reference left behind would silently resurrect onto an unrelated new instance/connection built
// later with the same id — see packages/ledger/apply.py). Without this, a cascade like that is
// completely invisible to the model: "self-check: ok" can look like success while the design quietly
// lost couplings/regions the user asked for. List the actual ids (not just a count) so the model
// knows WHAT to reconsider re-adding, not just that something happened.
function describeCascade(o: {
  removedConnectionIds?: string[];
  removedCouplingIds?: string[];
  removedRegionIds?: string[];
  removedFitBindingIds?: string[];
  removedJoinAnnotationIds?: string[];
}): string {
  const items: string[] = [];
  for (const id of o.removedConnectionIds ?? []) items.push(`connection ${id}`);
  for (const id of o.removedCouplingIds ?? []) items.push(`coupling ${id}`);
  for (const id of o.removedRegionIds ?? []) items.push(`region ${id}`);
  for (const id of o.removedFitBindingIds ?? []) items.push(`fit_binding ${id}`);
  for (const id of o.removedJoinAnnotationIds ?? []) items.push(`join_annotation ${id}`);
  if (items.length === 0) return "";
  return ` (cascade also removed: ${items.join(", ")} — re-add these if they're still needed for this design)`;
}

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
      entry += describeCascade(outcome);
      parts.push(entry);
    });
  }
  // Phase 1b (2026-07-19): connection outcomes MUST reach the model too, symmetric with instance/
  // feature ops — otherwise a REJECTED mate (e.g. a hallucinated interface name) never gets fed back
  // and the model re-proposes the identical wrong mate next turn, and an APPLIED mate's minted
  // connection_id is never learned so it can't target a later remove_connection (2026-07-19 review).
  if (m.connectionOps) {
    m.connectionOps.forEach((op, i) => {
      const outcome = m.connectionOpOutcomes?.[i];
      if (!outcome) return;
      const what = op.op === "add_connection"
        ? `connect ${op.a_instance}.${op.a_interface} <-> ${op.b_instance}.${op.b_interface}`
        : `remove_connection ${op.id}`;
      let entry = `${what} -> ${outcome.status}`;
      if (outcome.status === "APPLIED" && outcome.connectionId) entry += ` (connection_id=${outcome.connectionId})`;
      if (outcome.message && outcome.status !== "APPLIED") entry += `: ${outcome.message}`;
      entry += describeCascade(outcome);
      parts.push(entry);
    });
  }
  // Phase 2b: coupling outcomes MUST reach the model too, symmetric with connection/instance/feature
  // ops — otherwise a REJECTED coupling (e.g. a hallucinated relation or source param) never gets fed
  // back and the model re-proposes the identical wrong wiring next turn, and an APPLIED coupling's
  // minted coupling_id is never learned so it can't be referenced by a later remove_coupling.
  if (m.couplingOps) {
    m.couplingOps.forEach((op, i) => {
      const outcome = m.couplingOpOutcomes?.[i];
      if (!outcome) return;
      const what = op.op === "add_coupling"
        ? `couple ${op.target_instance} <- ${op.relation}`
        : `remove_coupling ${op.id}`;
      let entry = `${what} -> ${outcome.status}`;
      if (outcome.status === "APPLIED" && outcome.couplingId) entry += ` (coupling_id=${outcome.couplingId})`;
      if (outcome.message && outcome.status !== "APPLIED") entry += `: ${outcome.message}`;
      parts.push(entry);
    });
  }
  // 2026-07-27: fit outcomes MUST reach the model too, symmetric with connection/coupling/instance/
  // feature ops above — otherwise a REJECTED fit (e.g. a non-square host tripping the rotation-safety
  // gate, or a genuine invariant violation) never gets fed back and the model re-proposes the
  // identical wrong fit next turn, and an APPLIED fit's minted fit_id is never learned so it can't be
  // targeted by a later resync_fit/unfit_connector.
  if (m.fitOps) {
    m.fitOps.forEach((op, i) => {
      const outcome = m.fitOpOutcomes?.[i];
      if (!outcome) return;
      const what = op.op === "fit_connector" ? `fit ${op.connector_instance} <- ${op.host_instance}`
        : op.op === "resync_fit" ? `resync_fit ${op.id}` : `unfit_connector ${op.id}`;
      let entry = `${what} -> ${outcome.status}`;
      if (outcome.status === "APPLIED" && outcome.fitId) entry += ` (fit_id=${outcome.fitId})`;
      if (outcome.message && outcome.status !== "APPLIED") entry += `: ${outcome.message}`;
      parts.push(entry);
    });
  }

  // 2026-08-06 (gearbox-housing-generation initiative): envelope outcomes MUST reach the model too,
  // symmetric with fit/region/coupling/connection/instance/feature ops above — this is the exact
  // mechanism packages/agents/prompt_builder.py::_housing_pacing_section paces ("propose wrap_group
  // next"); without this feedback, a REJECTED wrap_group (e.g. an unknown housing_instance, or the
  // group not actually mate-connected yet) never gets fed back and the model re-proposes the
  // identical wrap_group turn after turn, exactly the stuck-loop failure this feedback loop exists
  // to prevent for every other op kind.
  if (m.envelopeOps) {
    m.envelopeOps.forEach((op, i) => {
      const outcome = m.envelopeOpOutcomes?.[i];
      if (!outcome) return;
      const what = op.op === "wrap_group"
        ? `wrap_group ${op.housing_instance} <- [${(op.member_instance_ids ?? []).join(", ")}]`
        : `${op.op} ${op.housing_instance}`;
      let entry = `${what} -> ${outcome.status}`;
      if (outcome.message && outcome.status !== "APPLIED") entry += `: ${outcome.message}`;
      parts.push(entry);
    });
  }

  // 2026-08-04: region outcomes MUST reach the model too, symmetric with connection/coupling/fit/
  // instance/feature ops above — otherwise a REJECTED region (e.g. an unknown host_instance, or
  // non-positive extents) never gets fed back and the model re-proposes the identical wrong region
  // next turn, and an APPLIED region's minted region_id is never learned so it can't be targeted by a
  // later remove_region.
  if (m.regionOps) {
    m.regionOps.forEach((op, i) => {
      const outcome = m.regionOpOutcomes?.[i];
      if (!outcome) return;
      const what = op.op === "add_region"
        ? `region ${op.host_instance}: ${op.label} (${op.kind})`
        : `remove_region ${op.id}`;
      let entry = `${what} -> ${outcome.status}`;
      if (outcome.status === "APPLIED" && outcome.regionId) entry += ` (region_id=${outcome.regionId})`;
      if (outcome.message && outcome.status !== "APPLIED") entry += `: ${outcome.message}`;
      parts.push(entry);
    });
  }

  return parts.length > 0 ? `[outcomes: ${parts.join("; ")}]` : null;
}
