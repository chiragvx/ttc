// Wire types — mirror packages/transport/protocol.py

export interface ParamMutationRequest {
  event_type?: "PARAMETER_MUTATION_REQUEST";
  target_node: string;
  requested_value: number;
  set_lock?: string | null;
}

export interface TelemetryDelta {
  total_mass_g: number;
  cg_mm: [number, number, number];
  estimated_print_time_s: number;
  estimated_cost_usd: number;   // Cost discipline — analytic readout
}

export interface MutationApplied {
  node: string;
  value: number;
  old_value?: number | null; // pre-change value, for Undo
  status: string; // APPLIED | APPLIED_ADVISORY
}

// A companion change a subsystem's deterministic CascadeRule made as a side effect of the direct
// edit (e.g. growing a bolt hole cascades the plate depth up to keep the edge-distance rule
// satisfied, instead of the request being rejected outright). Never LLM-originated.
export interface CascadeEffect {
  node: string;
  value: number;
  old_value?: number | null;
  reason: string;
}

export interface ValidRange {
  node: string;
  valid_min: number;
  valid_max: number;
}

// self-check report (2026-07-19) — geometric backbone always; visual half only when a vision model
// is configured. Mirrors packages/truth_plane/validate.py::ValidationReport.
export interface ValidationIssue {
  check: string;      // degeneracy | connectivity | embedding | visual
  severity: string;   // error | warning | info
  message: string;
  instances: string[];
}
export interface ValidationReport {
  ok: boolean;
  issues: ValidationIssue[];
  summary: string;
}
export interface ValidationResult {
  ok: boolean;
  geometric: ValidationReport;
  visual: ValidationReport | null;
  vision_enabled: boolean;
  vision_ran: boolean;
}

export interface CascadeUpdate {
  event_type: "PARAMETER_CASCADE_UPDATE";
  mutations_applied: MutationApplied[];
  cascades_applied: CascadeEffect[];
  telemetry_delta: TelemetryDelta;
  // refreshed invariant-valid slider clamps for every geometry param of the active instance — a drag
  // on one param can shift another's valid range, so all refresh together (2026-07-19). Optional so
  // an older backend response without it doesn't break parsing.
  valid_ranges?: ValidRange[];
}

export interface MutationRejected {
  event_type: "PARAMETER_MUTATION_REJECTED";
  target_node: string;
  status: string; // REJECTED | CONFLICT
  reason: string;
}

export type ServerMessage = CascadeUpdate | MutationRejected;

export interface ParameterDelta {
  target_node: string;
  requested_value: number;
  set_lock?: string | null;
  rationale?: string | null;
}

// Add/update/remove a hole/pocket/slot cut on any instance — mirrors
// packages/ledger/deltas.py::FeatureOp. Posted VERBATIM (as received in a "proposal" SSE event) to
// POST /feature_ops once the human accepts it — see packages/frontend/src/api.ts::applyFeatureOp.
export interface FeatureOp {
  op: "add_feature" | "update_feature" | "remove_feature";
  instance_id: string;
  kind?: "hole" | "pocket" | "slot" | null;   // required for add/update
  shape?: "circle" | "rect" | null;            // required for add/update
  dia_mm?: number | null;
  length_mm?: number | null;
  width_mm?: number | null;
  through?: boolean;
  depth_mm?: number | null;
  x_mm?: number;
  y_mm?: number;
  feature_id?: string | null;   // required for update_feature/remove_feature
  rationale?: string | null;
}

// The resolved cut, as stored on Instance.cut_features (packages/ledger/schema.py::CutFeature).
export interface CutFeature {
  id: string;
  kind: "hole" | "pocket" | "slot";
  shape: "circle" | "rect";
  dia_mm?: number | null;
  length_mm?: number | null;
  width_mm?: number | null;
  depth_mm: number;
  x_mm: number;
  y_mm: number;
}

// What POST /feature_ops returns, reshaped for the UI — the FeatureOp analog of DeltaOutcome.
export interface FeatureOpOutcome {
  op: FeatureOp;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  instanceId: string;
  feature: CutFeature | null;
  reason?: string;
}

// A snapshot of an Instance as returned by POST /instance_ops (packages/ledger/schema.py::Instance,
// reshaped) — just enough (subsystem_type + position) to reverse an add/remove/move via a fresh
// instance_ops call. `params`/`cut_features` are deliberately NOT included: InstanceOp has no way to
// set them on `add_instance`, so a removed instance's customizations can't be restored — Undo here
// is a practical re-add (new id, same type + position), never a literal undo. `transform` now carries
// rotation too (rx_deg/ry_deg/rz_deg), not just position — needed so a move_instance's Undo can
// restore the EXACT prior orientation, not just the prior x/y/z (see `previous_instance` on
// InstanceOpOutcome below). `transform` is null when the instance was living purely off auto-layout
// (never explicitly positioned) — Undo of a move in that case means "clear back to auto-layout", not
// "restore some numeric position".
export interface InstanceSnapshot {
  id: string;
  subsystem_type: string;
  parent_id?: string | null;
  transform?: { x_mm: number; y_mm: number; z_mm: number; rx_deg: number; ry_deg: number; rz_deg: number } | null;
}

// Add/remove/move an instance of an EXISTING subsystem type, to compose a multi-part assembly —
// mirrors packages/ledger/deltas.py::InstanceOp. Posted VERBATIM (as received in a "proposal" SSE
// event) to POST /instance_ops once the human accepts it — see
// packages/frontend/src/api.ts::applyInstanceOp.
//
// `move_instance` (2026-07-05) reuses every field below — no new fields needed:
//   - `instance_id` is REQUIRED (a REAL existing id — never invented).
//   - `x_mm`/`y_mm`/`z_mm` are REQUIRED, ALL THREE TOGETHER — unlike add_instance, there is NO
//     "omit all three -> auto-layout" fallback for move_instance; omitting all three is itself a
//     rejection.
//   - `rx_deg`/`ry_deg`/`rz_deg` are OPTIONAL, all-or-nothing. Omitted -> the instance KEEPS its
//     current rotation (never silently zeroed).
export interface InstanceOp {
  op: "add_instance" | "remove_instance" | "move_instance";
  subsystem_type?: string | null;   // add_instance only
  instance_id?: string | null;      // required for remove_instance AND move_instance; optional/
                                     // auto-generated for add_instance
  parent_id?: string | null;        // add_instance only (ignored for move_instance); omitted ->
                                     // top-level part (the common case); parts are a flat set, not a
                                     // tree — real parenting is opt-in, never assumed
  x_mm?: number | null;
  y_mm?: number | null;
  z_mm?: number | null;
  rx_deg?: number | null;
  ry_deg?: number | null;
  rz_deg?: number | null;
  rationale?: string | null;
}

// Add/remove a typed interface<->interface mate (Phase 1b, 2026-07-19) — mirrors
// packages/ledger/deltas.py::ConnectionOp. Posted to POST /connection_ops on accept. The engine's
// placement solver derives the mated part's position from the two declared frames.
export interface ConnectionOp {
  op: "add_connection" | "remove_connection";
  id?: string | null;              // required for remove_connection; auto-generated for add
  a_instance?: string | null;
  a_interface?: string | null;
  b_instance?: string | null;
  b_interface?: string | null;
  kind?: "mate" | "bolted" | "slip_fit" | "containment" | null;
  gap_mm?: number | null;
  rationale?: string | null;
}
export interface ConnectionOpOutcome {
  op: ConnectionOp;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  connectionId: string | null;
  message?: string;
}

// What POST /instance_ops returns, reshaped for the UI — the InstanceOp analog of FeatureOpOutcome.
export interface InstanceOpOutcome {
  op: InstanceOp;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  instanceId: string | null;
  subsystemType: string | null;
  instance?: InstanceSnapshot | null;   // pre-removal (or post-add, or post-move) snapshot, for Undo
  // The instance's PRE-move state (mainly its OLD transform), for an exact move_instance Undo.
  // Present ONLY on a successful move_instance — always null/undefined for add_instance and
  // remove_instance, and null on a REJECTED move_instance too.
  previousInstance?: InstanceSnapshot | null;
  reason?: string;
}

export interface ProposeResponse {
  deltas: ParameterDelta[];
  clarification: string | null;
  provider: string;
  no_llm?: boolean;
}

export interface MeshData {
  positions: number[];
  indices: number[];
}

// A pickable geometric feature (rough click-to-select groundwork — see
// packages/subsystems/features.py). "point" is in the SAME raw backend coordinate space as
// MeshData.positions (pre-viewport-display-transform).
export interface PickableFeature {
  instance_id: string;
  tag: string;
  point: [number, number, number];
  meta: Record<string, unknown>;
}

// --- chat (SSE) ---
export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "proposal"; deltas: ParameterDelta[]; feature_ops: FeatureOp[]; instance_ops: InstanceOp[]; connection_ops: ConnectionOp[]; clarification: string | null; suggestions: string[] }
  | { type: "no_llm" }
  | { type: "error"; message: string }
  | { type: "done" };

export interface DeltaOutcome {
  node: string;
  requested: number;
  applied: number | null;
  oldValue: number | null;
  status: "APPLIED" | "APPLIED_ADVISORY" | "REJECTED" | "CONFLICT";
  reason?: string;
  cascades?: CascadeEffect[]; // companion changes this SPECIFIC edit triggered, if any
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  clarification?: string | null;
  suggestions?: string[];
  outcomes?: DeltaOutcome[];
  featureOps?: FeatureOp[];               // AI-proposed cuts — auto-applied, index-aligned outcomes below
  // undefined entries are ops still mid-flight (a batch fills in outcomes as each one completes,
  // rather than appearing all at once only when the whole batch finishes — see chat/Chat.tsx)
  featureOpOutcomes?: (FeatureOpOutcome | undefined)[];
  instanceOps?: InstanceOp[];             // AI-proposed add/remove-instance ops — auto-applied likewise
  instanceOpOutcomes?: (InstanceOpOutcome | undefined)[];
  connectionOps?: ConnectionOp[];         // AI-proposed interface mates (Phase 1b) — auto-applied
  connectionOpOutcomes?: (ConnectionOpOutcome | undefined)[];
  validation?: ValidationResult;          // self-check run after this turn's geometry changes (2026-07-19)
}
