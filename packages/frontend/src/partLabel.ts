import type { InstanceRow } from "./api";

// A plain-language display name for an instance — "Round Post 2", not "round_post (round_post_2)".
// Shared by Outliner and PartDetail so the list and the detail panel always agree on a part's name.
export function partLabel(inst: InstanceRow, instances: InstanceRow[]): string {
  const humanized = inst.subsystem_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const sameType = instances.filter((i) => i.subsystem_type === inst.subsystem_type);
  if (sameType.length <= 1) return humanized;
  const ordinal = sameType.findIndex((i) => i.id === inst.id) + 1;
  return `${humanized} ${ordinal}`;
}
