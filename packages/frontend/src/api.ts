import type { ChatEvent, ConnectionOp, CouplingOp, CutFeature, FeatureOp, InstanceOp, InstanceSnapshot, LedgerGraphData, ManufacturingManifest, MeshData, PickableFeature, TelemetryDelta, ValidationResult } from "./types";
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

// --- ConnectionOp (2026-07-19): add/remove a typed interface<->interface mate. Posted VERBATIM as
// received in a "proposal" SSE event; the placement solver derives the mated part's position.
export interface ConnectionOpApplyResponse {
  ok: boolean;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  connection_id: string | null;
  connection: unknown | null;
  message: string;
}
export async function applyConnectionOp(op: ConnectionOp): Promise<ConnectionOpApplyResponse> {
  const res = await apiFetch("/connection_ops", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(op),
  });
  // a backend without this route (older build) returns 404/HTML — surface a clear message instead of
  // a cryptic JSON-parse error (2026-07-19 review)
  if (!res.ok) throw new Error(`connection endpoint unavailable (HTTP ${res.status})`);
  return res.json();
}

// --- CouplingOp (Phase 2b): wire a part's load to be derived from another part's condition. Posted
// VERBATIM as received in a "proposal" SSE event; mirrors applyConnectionOp above.
export interface CouplingOpApplyResponse {
  ok: boolean;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  coupling_id: string | null;
  coupling: unknown | null;
  message: string;
}
export async function applyCouplingOp(op: CouplingOp): Promise<CouplingOpApplyResponse> {
  const res = await apiFetch("/coupling_ops", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(op),
  });
  // a backend without this route (older build) returns 404/HTML — surface a clear message instead of
  // a cryptic JSON-parse error (mirrors applyConnectionOp's 2026-07-19 review fix)
  if (!res.ok) throw new Error(`coupling endpoint unavailable (HTTP ${res.status})`);
  return res.json();
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
// 2026-07-19 — /signoff now 409s when the design hasn't actually been analyzed at its current
// geometry (packages/transport/app.py::signoff). apiFetch doesn't throw on a non-2xx (see fetchMesh
// above for this file's usual "caller checks res.ok" convention), so this used to silently resolve
// even on a blocked sign-off -- the caller never knew review.state didn't actually flip.
export interface SignoffResult {
  ok: boolean;
  message?: string;
  unknowns?: string[];
}
export async function signoff(): Promise<SignoffResult> {
  const res = await apiFetch("/signoff?reviewer=engineer", { method: "POST" });
  if (!res.ok) {
    const body = await res.json();
    return { ok: false, message: body.message, unknowns: body.unknowns };
  }
  return { ok: true };
}

// --- EKG graph view (topology) — READ-ONLY: the full instance/connection/coupling graph behind the
// Graph tab (EKGGraphView.tsx). Mirrors GET /ledger (packages/transport/app.py::get_ledger), which
// returns the whole ledger via model_dump(); LedgerGraphData only types the subset the graph view
// reads, so the extra fields (params/transform/cut_features/...) are ignored via structural typing.
export async function getLedger(): Promise<LedgerGraphData> {
  const res = await apiFetch("/ledger");
  // AUTH_TOKEN/session-limit modes return a normal 200-parseable JSON error body ({"detail": "..."})
  // on 401/503 — unchecked, that gets stored and handed to EKGGraphView as a malformed LedgerGraphData,
  // crashing its render (Object.keys(undefined) etc.) with no ErrorBoundary anywhere to contain it
  // (2026-07-19 review, CRITICAL).
  if (!res.ok) throw new Error(`ledger unavailable (HTTP ${res.status})`);
  return res.json();
}

// --- manufacturability outputs (Phase 6) — READ-ONLY make-manifest: each part's material/process
// plus the assembly steps derived from the connection graph. Mirrors getRequirements() above.
export async function getManufacturingManifest(): Promise<ManufacturingManifest> {
  const res = await apiFetch("/manufacturing/manifest");
  // a backend without this route (older build) returns 404/HTML — surface a clear message instead of
  // silently parsing an error body as a valid manifest (2026-07-19 review, mirrors applyConnectionOp's
  // same-day fix — fetch() only rejects on network failure, never on a non-2xx status).
  if (!res.ok) throw new Error(`manufacturing manifest unavailable (HTTP ${res.status})`);
  return res.json();
}

// Self-check the current assembly (2026-07-19). Geometric check always runs (no model); the visual
// check runs only if a vision model is configured server-side (VISION_MODEL) and a key is passed.
export async function runValidate(intent: string, apiKey?: string | null): Promise<ValidationResult> {
  const res = await apiFetch("/validate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent, api_key: apiKey ?? null }),
  });
  // same class of bug as getManufacturingManifest/getLedger's same-day fix: a 401/503 error body
  // parses fine as JSON and would otherwise be stored as a fake ValidationResult, crashing
  // ValidationCard's unconditional result.geometric.issues access (2026-07-19 review, HIGH).
  if (!res.ok) throw new Error(`validate unavailable (HTTP ${res.status})`);
  return res.json();
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
