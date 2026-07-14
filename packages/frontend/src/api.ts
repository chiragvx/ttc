import type { ChatEvent, CutFeature, FeatureOp, InstanceOp, InstanceSnapshot, MeshData, PickableFeature, TelemetryDelta } from "./types";
import type { LlmSettings } from "./settings";

// REST + SSE calls to the FastAPI backend (proxied by Vite in dev).

// the ACTIVE subsystem's geometry, tessellated from the current ledger (registry-driven backend)
export async function fetchMesh(): Promise<MeshData> {
  const res = await fetch(`/mesh`);
  if (!res.ok) throw new Error(`mesh failed: ${res.status}`);
  return res.json();
}

// rough click-to-select groundwork: every tagged geometric feature with a world-space point
export async function fetchMeshFeatures(): Promise<PickableFeature[]> {
  const res = await fetch(`/mesh/features`);
  if (!res.ok) throw new Error(`mesh features failed: ${res.status}`);
  return (await res.json()).features;
}

// --- subsystem (part type) selection + its tunable params ---
export interface ParamSpec {
  node: string; value: number; min: number; max: number; step: number;
  unit: string; locked: boolean; label: string;
}
export interface SubsystemInfo { name: string; description: string; disciplines: string[]; }

export async function getParams(): Promise<{ subsystem: string | null; instance_id: string | null; params: ParamSpec[] }> {
  return (await fetch("/params")).json();
}
// `active` is null on an empty file — no parts yet (see packages/transport/app.py::make_demo_ledger).
export async function getSubsystems(): Promise<{ active: string | null; available: SubsystemInfo[] }> {
  return (await fetch("/subsystems")).json();
}

// --- Files (2026-07-04): a session can hold several independent design files (think browser tabs),
// each with its own parts/goal/history. Replaces the old single-project "New Project" reset entirely
// — "start completely over" is just opening a new file.
export interface FileRow { id: string; name: string; part_count: number; is_active: boolean; }
export async function listFiles(): Promise<{ files: FileRow[] }> {
  return (await fetch("/files")).json();
}
export async function createFile(): Promise<{ ok: boolean; id: string; name: string }> {
  return (await fetch("/files", { method: "POST" })).json();
}
export async function openFile(id: string): Promise<{ ok: boolean; id?: string; error?: string }> {
  return (await fetch(`/files/${encodeURIComponent(id)}/open`, { method: "POST" })).json();
}

// --- Item 3: the multi-instance outliner (add/remove/activate a second independent part) ---
export interface InstanceRow {
  id: string; subsystem_type: string; parent_id: string | null; is_active: boolean;
  cut_feature_count: number;
  world_offset: [number, number, number];  // raw backend mm coords — same space as MeshData.positions
}
export async function listInstances(): Promise<{ instances: InstanceRow[] }> {
  return (await fetch("/instances")).json();
}
export async function addInstance(
  subsystemType: string, parentId?: string | null,
): Promise<{ ok: boolean; instance_id?: string; error?: string }> {
  return (await fetch("/instances", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subsystem_type: subsystemType, parent_id: parentId ?? null }),
  })).json();
}
export async function removeInstance(id: string): Promise<{ ok: boolean; error?: string }> {
  return (await fetch(`/instances/${encodeURIComponent(id)}`, { method: "DELETE" })).json();
}
export async function activateInstance(id: string): Promise<{ ok: boolean; instance_id?: string; error?: string }> {
  return (await fetch(`/instances/${encodeURIComponent(id)}/activate`, { method: "POST" })).json();
}

// --- FeatureOp: human-accepted hole/pocket/slot cuts (mirrors POST /instances, not the WS path — a
// feature op is a discrete accepted action, not a 30 Hz slider stream). Posts the FeatureOp exactly
// as received in a "proposal" SSE event; see packages/transport/app.py::create_feature_op.
export interface FeatureOpApplyResponse {
  ok: boolean;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  instance_id: string;
  feature: CutFeature | null;
  message: string;
}
export async function applyFeatureOp(op: FeatureOp): Promise<FeatureOpApplyResponse> {
  return (await fetch("/feature_ops", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(op),
  })).json();
}

// --- InstanceOp: human-accepted assembly composition (add/remove/move an instance) — mirrors
// applyFeatureOp above (same "propose then explicit accept" REST shape). Posts the InstanceOp
// exactly as received in a "proposal" SSE event; see packages/transport/app.py::create_instance_op.
export interface InstanceOpApplyResponse {
  ok: boolean;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  instance_id: string | null;
  instance: InstanceSnapshot | null;
  // NEW (2026-07-05, move_instance): the instance's PRE-move state, for exact Undo. Present
  // (non-null) ONLY on a successful move_instance — always null for add_instance/remove_instance,
  // and null on any REJECTED move_instance too.
  previous_instance: InstanceSnapshot | null;
  message: string;
}
export async function applyInstanceOp(op: InstanceOp): Promise<InstanceOpApplyResponse> {
  return (await fetch("/instance_ops", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(op),
  })).json();
}

// --- truth-plane analysis loop ---
export async function analyze(loadN = 40): Promise<any> {
  return (await fetch(`/analyze?load_n=${loadN}`, { method: "POST" })).json();
}
export async function analyzeStatus(): Promise<any> {
  return (await fetch("/analyze/status")).json();
}
export async function optimize(loadN = 25): Promise<any> {
  return (await fetch(`/optimize?load_n=${loadN}`, { method: "POST" })).json();
}
export async function optimizeStatus(): Promise<any> {
  return (await fetch("/optimize/status")).json();
}
export async function exportCheck(): Promise<{ status: string; reasons: string[]; unknowns: string[] }> {
  return (await fetch("/export/check", { method: "POST" })).json();
}

// REST-fetchable telemetry (2026-07-04) — the WS path already pushes this on every parameter
// mutation, but adding/removing a part via REST (instance_ops / the outliner) never touches that
// socket, so this lets the UI refresh Mass/CG/Print/Cost right after a part change too.
export async function fetchTelemetry(): Promise<TelemetryDelta> {
  return (await fetch("/telemetry")).json();
}

// --- goal-grounded requirements (the design agent's targets, judged vs live metrics) ---
export interface RequirementRow {
  id: string; text: string; metric: string; op: string; target: number;
  method: string; status: "SATISFIED" | "VIOLATED" | "UNKNOWN"; value: number | null;
}
export interface RequirementsData {
  goal_set: boolean; implied_fs_floor: number | null; enforced_fs_floor: number;
  satisfied: number; total: number; requirements: RequirementRow[];
  metrics: Record<string, number | null>;
}
export async function setGoal(goal: string): Promise<RequirementsData> {
  return (await fetch("/requirements", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal }),
  })).json();
}
export async function getRequirements(): Promise<RequirementsData> {
  return (await fetch("/requirements")).json();
}
export async function signoff(): Promise<void> {
  await fetch("/signoff?reviewer=engineer", { method: "POST" });
}

// Stream a conversational reply. Calls onEvent for each SSE event; abortable via signal.
export async function streamChat(
  messages: Array<{ role: string; content: string }>,
  settings: LlmSettings,
  onEvent: (e: ChatEvent) => void | Promise<void>,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, api_key: settings.apiKey || null, model: settings.model || null }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`chat failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const frames = buf.split("\n\n");
    buf = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      let event: ChatEvent;
      try {
        event = JSON.parse(line.slice(6)) as ChatEvent;
      } catch {
        continue; // ignore malformed frame
      }
      // MUST be awaited (and outside the parse try/catch above, so a real failure inside onEvent's
      // own handling propagates instead of being swallowed as "malformed frame"): onEvent's handling
      // of a "proposal" frame does further async work (onApply/onApplyFeatureOp/onApplyInstanceOp
      // round trips) before it finishes updating the message. If this loop raced ahead to the next
      // frame (typically the immediately-following "done"), the "done" handler would read the
      // message mid-update and mistake a genuinely in-flight, about-to-succeed turn for an empty
      // one. Awaiting here keeps events landing in the same order the backend produced them, each
      // fully processed before the next begins.
      await onEvent(event);
    }
  }
}
