import type { ChatEvent, CutFeature, FeatureOp, InstanceOp, InstanceSnapshot, MeshData, PickableFeature, TelemetryDelta, ValidationResult } from "./types";
import { loadSettings, type LlmSettings } from "./settings";

// REST + SSE calls to the FastAPI backend (proxied by Vite in dev).

// Attaches `Authorization: Bearer <authToken>` (2026-07-15) when the operator's backend has
// AUTH_TOKEN configured and the user has entered it in settings — a no-op (empty header value is
// simply omitted) against the default, unauthenticated backend. The session cookie itself (set by
// the backend on the first authenticated call) rides along automatically on every same-origin
// fetch; this header is only what lets the FIRST call ever succeed when auth is configured.
function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const { authToken } = loadSettings();
  const headers = authToken
    ? { ...(init.headers ?? {}), Authorization: `Bearer ${authToken}` }
    : init.headers;
  return fetch(url, { ...init, headers });
}

// the ACTIVE subsystem's geometry, tessellated from the current ledger (registry-driven backend).
// Optional AbortSignal is available for callers that want to drop a superseded response; the live-
// drag viewport instead uses single-flight + a liveness flag (see Viewport.tsx), so it passes none.
export async function fetchMesh(signal?: AbortSignal): Promise<MeshData> {
  const res = await apiFetch(`/mesh`, { signal });
  if (!res.ok) throw new Error(`mesh failed: ${res.status}`);
  return res.json();
}

// rough click-to-select groundwork: every tagged geometric feature with a world-space point
export async function fetchMeshFeatures(signal?: AbortSignal): Promise<PickableFeature[]> {
  const res = await apiFetch(`/mesh/features`, { signal });
  if (!res.ok) throw new Error(`mesh features failed: ${res.status}`);
  return (await res.json()).features;
}

// --- subsystem (part type) selection + its tunable params ---
export interface ParamSpec {
  node: string; value: number; min: number; max: number; step: number;
  unit: string; locked: boolean; label: string;
  // PHYSICALLY-VALID slider clamp (2026-07-19) — the sub-range where the subsystem's cross-field
  // invariants hold given every other param's current value (packages/subsystems/valid_ranges.py).
  // NOT the advisory [min,max] recommended envelope: a value can be inside [valid_min,valid_max] but
  // outside [min,max] (shows the ⚠ cue), never outside the valid range via a drag. Optional so an
  // older backend / a cross-cutting param without a computed range falls back to [min,max].
  valid_min?: number; valid_max?: number;
}
export interface SubsystemInfo { name: string; description: string; disciplines: string[]; }

export async function getParams(): Promise<{ subsystem: string | null; instance_id: string | null; params: ParamSpec[] }> {
  return (await apiFetch("/params")).json();
}
// `active` is null on an empty file — no parts yet (see packages/transport/app.py::make_demo_ledger).
export async function getSubsystems(): Promise<{ active: string | null; available: SubsystemInfo[] }> {
  return (await apiFetch("/subsystems")).json();
}

// --- Files (2026-07-04): a session can hold several independent design files (think browser tabs),
// each with its own parts/goal/history. Replaces the old single-project "New Project" reset entirely
// — "start completely over" is just opening a new file.
export interface FileRow { id: string; name: string; part_count: number; is_active: boolean; }
export async function listFiles(): Promise<{ files: FileRow[] }> {
  return (await apiFetch("/files")).json();
}
export async function createFile(): Promise<{ ok: boolean; id: string; name: string }> {
  return (await apiFetch("/files", { method: "POST" })).json();
}
export async function openFile(id: string): Promise<{ ok: boolean; id?: string; error?: string }> {
  return (await apiFetch(`/files/${encodeURIComponent(id)}/open`, { method: "POST" })).json();
}

// --- Item 3: the multi-instance outliner (add/remove/activate a second independent part) ---
export interface InstanceRow {
  id: string; subsystem_type: string; parent_id: string | null; is_active: boolean;
  cut_feature_count: number;
  world_offset: [number, number, number];  // raw backend mm coords — same space as MeshData.positions
}
export async function listInstances(): Promise<{ instances: InstanceRow[] }> {
  return (await apiFetch("/instances")).json();
}
export async function addInstance(
  subsystemType: string, parentId?: string | null,
): Promise<{ ok: boolean; instance_id?: string; error?: string }> {
  return (await apiFetch("/instances", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subsystem_type: subsystemType, parent_id: parentId ?? null }),
  })).json();
}
export async function removeInstance(id: string): Promise<{ ok: boolean; error?: string }> {
  return (await apiFetch(`/instances/${encodeURIComponent(id)}`, { method: "DELETE" })).json();
}
export async function activateInstance(id: string): Promise<{ ok: boolean; instance_id?: string; error?: string }> {
  return (await apiFetch(`/instances/${encodeURIComponent(id)}/activate`, { method: "POST" })).json();
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
  return (await apiFetch("/feature_ops", {
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
  return (await apiFetch("/instance_ops", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(op),
  })).json();
}

// --- truth-plane analysis loop ---
// loadN is left OMITTED by default (not a hardcoded 40/25) so the backend resolves it itself —
// FileState.effective_load_n(): whatever the stated goal demands (e.g. "holds 200 N"), else its own
// historical default. Passing loadN explicitly still overrides that, same as before (2026-07-15 fix
// — this used to always send a hardcoded constant, which silently overrode any goal-derived load).
export async function analyze(loadN?: number): Promise<any> {
  const q = loadN != null ? `?load_n=${loadN}` : "";
  return (await apiFetch(`/analyze${q}`, { method: "POST" })).json();
}
export async function analyzeStatus(loadN?: number): Promise<any> {
  // must match the load_n analyze() actually resolved to (its response echoes it back as `load_n`) —
  // the backend only reports a verdict "current" if it was solved for this exact case, not just any
  // verdict for the current geometry.
  const q = loadN != null ? `?load_n=${loadN}` : "";
  return (await apiFetch(`/analyze/status${q}`)).json();
}
export async function optimize(loadN?: number): Promise<any> {
  const q = loadN != null ? `?load_n=${loadN}` : "";
  return (await apiFetch(`/optimize${q}`, { method: "POST" })).json();
}
export async function optimizeStatus(): Promise<any> {
  return (await apiFetch("/optimize/status")).json();
}
export async function exportCheck(): Promise<{ status: string; reasons: string[]; unknowns: string[] }> {
  return (await apiFetch("/export/check", { method: "POST" })).json();
}

// REST-fetchable telemetry (2026-07-04) — the WS path already pushes this on every parameter
// mutation, but adding/removing a part via REST (instance_ops / the outliner) never touches that
// socket, so this lets the UI refresh Mass/CG/Print/Cost right after a part change too.
export async function fetchTelemetry(): Promise<TelemetryDelta> {
  return (await apiFetch("/telemetry")).json();
}

// --- goal-grounded requirements (the design agent's targets, judged vs live metrics) ---
export interface RequirementRow {
  id: string; text: string; metric: string; op: string; target: number;
  method: string; status: "SATISFIED" | "VIOLATED" | "UNKNOWN"; value: number | null;
}
export interface RequirementsData {
  goal_set: boolean; implied_fs_floor: number | null; enforced_fs_floor: number;
  implied_load_n: number | null;  // the applied load the goal stated (e.g. "holds 200 N"), if any
  satisfied: number; total: number; requirements: RequirementRow[];
  metrics: Record<string, number | null>;
}
export async function setGoal(goal: string): Promise<RequirementsData> {
  return (await apiFetch("/requirements", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal }),
  })).json();
}
export async function getRequirements(): Promise<RequirementsData> {
  return (await apiFetch("/requirements")).json();
}
export async function signoff(): Promise<void> {
  await apiFetch("/signoff?reviewer=engineer", { method: "POST" });
}

// Self-check the current assembly (2026-07-19). Geometric check always runs (no model); the visual
// check runs only if a vision model is configured server-side (VISION_MODEL) and a key is passed.
export async function runValidate(intent: string, apiKey?: string | null): Promise<ValidationResult> {
  return (await apiFetch("/validate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent, api_key: apiKey ?? null }),
  })).json();
}

// Stream a conversational reply. Calls onEvent for each SSE event; abortable via signal.
export async function streamChat(
  messages: Array<{ role: string; content: string }>,
  settings: LlmSettings,
  onEvent: (e: ChatEvent) => void | Promise<void>,
  signal: AbortSignal,
): Promise<void> {
  const res = await apiFetch("/chat", {
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
