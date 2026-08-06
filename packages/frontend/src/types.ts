// Wire types — mirror packages/transport/protocol.py

export interface ParamMutationRequest {
  event_type?: "PARAMETER_MUTATION_REQUEST";
  target_node: string;
  requested_value: number | string; // string for the one string-valued node, material_profile
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
  value: number | string; // string for the one string-valued node, material_profile
  old_value?: number | string | null; // pre-change value, for Undo
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
  // 2026-07-27 — a coarse, closed-form FS estimate for every instance carrying a coupling-derived
  // load, "check": "structural" — always present (never null: it just reports zero issues when
  // there's nothing coupled yet), unlike `visual` which is genuinely absent when no vision model is
  // configured. See packages/transport/app.py::_coarse_structural_summary.
  structural: ValidationReport;
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

// 2026-08-01 — mirrors packages/ledger/parameter.py::ParamSource. A scoped passthrough provenance
// tag, NOT a confidence-scoring system: purely descriptive, nothing here ranks/sorts/aggregates on
// it. Absent or "unsourced" are equivalent and mean "render nothing".
export type ParamSource = "verified" | "rule_derived" | "solver_validated" | "unsourced";

export interface ParameterDelta {
  target_node: string;
  requested_value: number | string; // string for the one string-valued node, material_profile
  set_lock?: string | null;
  rationale?: string | null;
  // where this delta's requested value came from (mirrors packages/ledger/deltas.py::ParameterDelta.source).
  // Optional/defaulted server-side to "unsourced" — absent on any older payload.
  source?: ParamSource | null;
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
//
// `clear_transform` (2026-08-05) — mirrors packages/ledger/deltas.py::InstanceOp — is the SAFE
// escape hatch from the self-check's "two mated instances both carry an explicit transform" trap:
// un-anchors an instance back to pure mate-/auto-layout-resolved positioning WITHOUT the
// destruction a remove_instance + re-add would cause (every coupling/region/fit_binding/
// join_annotation/param wired to the instance is left untouched). Only `instance_id` is used (same
// required/unknown-id validation as move_instance); no position fields apply.
export interface InstanceOp {
  op: "add_instance" | "remove_instance" | "move_instance" | "clear_transform";
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
  // Cascade cleanup (2026-08-05) — a remove_connection cascade-deletes any JoinAnnotation that
  // referenced the now-gone connection_id (join_annotation ids get REUSED, so a stale reference left
  // behind would silently resurrect onto an unrelated new connection later). Optional/empty on every
  // outcome that didn't cascade-remove anything (add_connection, or a remove with no annotations).
  removedJoinAnnotationIds?: string[];
}

// Wire a part's load to be derived from another part's condition (Phase 2b) — mirrors
// packages/ledger/deltas.py::CouplingOp. Posted to POST /coupling_ops on accept, same "propose then
// explicit accept" boundary as ConnectionOp above.
export interface CouplingInputItem {
  name: string;
  value?: number | null;
  from_instance?: string | null;
  from_param?: string | null;
  rationale?: string | null; // never persisted/read — a legal place for the LLM's per-input reasoning
}
export interface CouplingOp {
  op: "add_coupling" | "remove_coupling";
  id?: string | null;              // required for remove_coupling; auto-generated for add
  target_instance?: string | null;
  relation?: string | null;
  inputs?: CouplingInputItem[];
  rationale?: string | null;
}
export interface CouplingOpOutcome {
  op: CouplingOp;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  couplingId: string | null;
  message?: string;
}

// Wire/unwire/resync a typed FIT BINDING (2026-07-27) — a CONNECTOR's fitted-dimension params
// derived ONCE from a HOST's cross-section, written as ordinary deltas. Posted to POST /fit_ops on
// accept, same "propose then explicit accept" boundary as ConnectionOp/CouplingOp above. Mirrors
// packages/ledger/deltas.py::FitOp.
export interface FitOp {
  op: "fit_connector" | "unfit_connector" | "resync_fit";
  id?: string | null;              // required for unfit_connector/resync_fit; auto-generated for fit_connector
  connector_instance?: string | null;
  host_instance?: string | null;
  clearance_mm?: number | null;
  rationale?: string | null;
}
export interface FitOpOutcome {
  op: FitOp;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  fitId: string | null;
  message?: string;
}

// Wire/unwire/resync a HOUSING instance's `wraps` list (2026-08-06, gearbox-housing-generation
// initiative) — which member instances a housing-family subsystem (declares envelope_socket) is
// declared to wrap/contain. Posted to POST /envelope_ops on accept, same "propose then explicit
// accept" boundary as FitOp/RegionOp above. Mirrors packages/ledger/deltas.py::EnvelopeOp.
// `wrap_group` SETS/REPLACES `member_instance_ids` wholesale (not an incremental add). `resync_envelope`
// re-triggers the derivation job without touching `wraps`.
export interface EnvelopeOp {
  op: "wrap_group" | "unwrap_group" | "resync_envelope";
  housing_instance: string;
  member_instance_ids?: string[] | null;   // required for wrap_group; ignored otherwise
  rationale?: string | null;
}
export interface EnvelopeOpOutcome {
  op: EnvelopeOp;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  housingInstanceId: string | null;
  message?: string;
}

// Add/remove a JoinAnnotation (2026-07-27) — records HOW two already-connected parts are joined
// (bolted/press_fit/welded/adhesive/custom) for the BOM; purely semantic, never touches geometry
// (contrast FitOp above). Posted to POST /join_annotation_ops on accept, same "propose then explicit
// accept" boundary as FitOp/CouplingOp. Mirrors packages/ledger/deltas.py::JoinAnnotationOp.
export interface JoinAnnotationOp {
  op: "add_join_annotation" | "remove_join_annotation";
  id?: string | null;              // required for remove_join_annotation; auto-generated for add
  connection_id?: string | null;
  method?: "bolted" | "press_fit" | "welded" | "adhesive" | "custom" | null;
  fastener?: string | null;
  note?: string | null;
  rationale?: string | null;
}
export interface JoinAnnotationOpOutcome {
  op: JoinAnnotationOp;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  joinId: string | null;
  message?: string;
}

// Add/remove a named keep-out/keep-in box on a HOST instance's own local frame (2026-08-04) — a pure
// geometric ANNOTATION (contrast CouplingOp, which derives a load, or FitOp, which derives a
// dimension): it derives nothing and nothing derives it. Posted to POST /region_ops on accept, same
// "propose then explicit accept" boundary as ConnectionOp/CouplingOp/FitOp/JoinAnnotationOp above.
// Mirrors packages/ledger/deltas.py::RegionOp. `x_mm`/`y_mm`/`z_mm` are the box's CENTER;
// `dx_mm`/`dy_mm`/`dz_mm` are its full extents (not half-extents) — both in the HOST's own local frame.
export interface RegionOp {
  op: "add_region" | "remove_region";
  id?: string | null;              // required for remove_region; auto-generated for add
  host_instance?: string | null;   // required for add_region
  kind?: "keep_out" | "keep_in" | null;
  label?: string | null;           // required for add_region, e.g. "gear_train_clearance"
  x_mm?: number | null;
  y_mm?: number | null;
  z_mm?: number | null;
  dx_mm?: number | null;
  dy_mm?: number | null;
  dz_mm?: number | null;
  rationale?: string | null;
}
export interface RegionOpOutcome {
  op: RegionOp;
  status: "APPLIED" | "REJECTED" | "CONFLICT";
  regionId: string | null;
  message?: string;
}

// The resolved fit wiring, as stored on MasterParametricLedger.fit_bindings — mirrors
// packages/ledger/schema.py::FitInput/FitBinding.
export interface FitInput {
  host_param: string;
  connector_param: string;
}
export interface FitBinding {
  id: string;
  connector_instance: string;
  host_instance: string;
  kind: "round" | "rect";
  inputs: FitInput[];
  clearance_mm: number;
}

// A proposed part manifest for a big/ambiguous "make an X" request (Phase 5, 2026-07-19) — PURE
// DISPLAY DATA, unlike ConnectionOp/CouplingOp: there is no apply endpoint, no outcome/status to
// track, no Undo. It just shows what the copilot intends to build before/alongside actually
// building it. Mirrors whatever packages/agents emits as ScopeProposal/ScopePartProposal.
export interface ScopePartProposal {
  subsystem_type: string;
  role: string;
  count: number;
  operating_conditions: string[];
  rationale?: string | null;
}
export interface ScopeProposal {
  goal: string;
  parts: ScopePartProposal[];
  out_of_scope: string[];
  open_questions: string[];
}

// Reference research (2026-08-01) — an OPTIONAL, advisory finding fetched automatically before a
// NEW compound design, so the copilot stops forcing the nearest generic catalog primitive onto
// something structurally different (see packages/agents/research_provider.py's module docstring —
// the "laptop stand is not a table" failure this targets). PURE DISPLAY DATA, same as
// ScopeProposal: no apply endpoint, no outcome, no Undo. Mirrors
// packages/agents/research_provider.py::ResearchFinding exactly. `suggested_subsystem_types` is
// UNVERIFIED — it may name a catalog part type or not; only ever used as a hint to the model, never
// trusted client-side either.
export interface ResearchFinding {
  query: string;
  summary: string;
  suggested_subsystem_types: string[];
  source_urls: string[];
  image_urls: string[];
  disclaimer: string;
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
  // Cascade cleanup (2026-08-05) — a remove_instance cascade-deletes any connections/couplings/
  // regions/fit_bindings/join_annotations that referenced the now-gone instance_id (all of these ids
  // get REUSED, lowest-free, so a stale reference left behind would silently resurrect onto an
  // unrelated new instance built later with the same id — see packages/ledger/apply.py's
  // remove_instance branch). Each is optional/empty on every outcome that didn't cascade-remove
  // anything of that kind (add_instance, move_instance, or a remove with nothing attached).
  removedConnectionIds?: string[];
  removedCouplingIds?: string[];
  removedRegionIds?: string[];
  removedFitBindingIds?: string[];
  removedJoinAnnotationIds?: string[];
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

// --- manufacturability outputs (Phase 6) — READ-ONLY: material/process per part plus the assembly
// order derived from the connection graph. Always backend-computed (GET /manufacturing/manifest);
// the frontend never derives material/process/assembly-order itself. Mirrors whatever
// packages/transport/app.py's manifest route returns.
export interface ManufacturingPart {
  instance_id: string;
  subsystem_type: string;
  material: string;
  process: "CNC" | "print";
}
export interface ManufacturingManifest {
  material: string;
  parts: ManufacturingPart[];
  assembly_steps: string[];
}

// --- EKG graph view (topology, distinct from the 3D viewport) — mirrors the subset of
// packages/ledger/schema.py::Instance/Connection/InterfaceRef/Coupling/CouplingInput that GET
// /ledger returns (a full model_dump — these interfaces only declare the fields the graph view
// reads; the real payload has more, e.g. Instance.params/transform/parent_id/cut_features, which
// structural typing lets us ignore here).
export interface LedgerParameter {
  value: number;
  unit: string;
}
export interface LedgerInstance {
  id: string;
  subsystem_type: string;
  params?: Record<string, LedgerParameter>;
}
export interface LedgerInterfaceRef {
  instance_id: string;
  interface: string;
}
export interface LedgerConnection {
  id: string;
  a: LedgerInterfaceRef;
  b: LedgerInterfaceRef;
  kind: string;
  gap_mm: number;
}
// Mirrors packages/ledger/schema.py::Region — a named keep-out/keep-in box on a HOST instance's own
// local frame (2026-08-04). x_mm/y_mm/z_mm are the box's CENTER; dx_mm/dy_mm/dz_mm are its full
// extents (not half-extents), both in the host's own local frame (same convention as CutFeature).
export interface LedgerRegion {
  id: string;
  host_instance: string;
  kind: string;
  label: string;
  x_mm: number;
  y_mm: number;
  z_mm: number;
  dx_mm: number;
  dy_mm: number;
  dz_mm: number;
}
export interface LedgerCouplingInput {
  value?: number | null;
  from_instance?: string | null;
  from_param?: string | null;
}
export interface LedgerCoupling {
  id: string;
  target_instance: string;
  relation: string;
  inputs: Record<string, LedgerCouplingInput>;
}
// Mirrors packages/ledger/schema.py::JoinAnnotation -- BOM/documentation-grade "how actually joined"
// data (bolted/press_fit/welded/adhesive/custom) attached to an EXISTING Connection via
// `connection_id` (2026-07-27; wired into the graph view 2026-08-01). Never geometry-touching.
export interface LedgerJoinAnnotation {
  id: string;
  connection_id: string;
  method: string;
  fastener?: string | null;
  note?: string | null;
}
export interface LedgerGraphData {
  instances: Record<string, LedgerInstance>;
  connections: LedgerConnection[];
  couplings: LedgerCoupling[];
  fit_bindings: FitBinding[];
  join_annotations: LedgerJoinAnnotation[];
  // Optional (unlike every field above) — GET /ledger's full model_dump always sends this, but
  // EKGGraphView.tsx/EKGGraphView.test.tsx (owned by a different file-set this session) don't read or
  // fixture it yet, so making it required here would break their existing `Partial<LedgerGraphData>`
  // test fixtures. Flip to required + backfill `regions: []` in that file's makeLedger() once the
  // graph view actually renders Region boxes/nodes.
  regions?: LedgerRegion[];
}

// --- chat (SSE) ---
// A single part of a multimodal chat message's `content`, when it's an array rather than a plain
// string — mirrors OpenRouter's own content-part shape (and
// packages/agents/openrouter_provider.py::judge_image's identical JSON) exactly: `{type:"text",
// text}` or `{type:"image_url", image_url:{url}}`. Only ever built client-side by
// chat/buildChatContent.ts; the backend does zero inspection of `content`'s shape, it's pure
// pass-through to OpenRouter (2026-08-05).
export interface ChatContentPart {
  type: "text" | "image_url";
  text?: string;
  image_url?: { url: string };
}

export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "proposal"; deltas: ParameterDelta[]; feature_ops: FeatureOp[]; instance_ops: InstanceOp[]; connection_ops: ConnectionOp[]; coupling_ops: CouplingOp[]; fit_ops: FitOp[]; envelope_ops: EnvelopeOp[]; join_annotation_ops: JoinAnnotationOp[]; region_ops: RegionOp[]; scope_proposal: ScopeProposal | null; clarification: string | null; suggestions: string[] }
  // Fired BEFORE any token/proposal events, at most once per turn, only when a research vendor is
  // actually configured server-side (see packages/transport/app.py's /chat handler) — most turns
  // never see this event at all. The fields are ResearchFinding's own, flattened onto the event.
  | ({ type: "research" } & ResearchFinding)
  | { type: "no_llm" }
  | { type: "error"; message: string }
  | { type: "done" };

export interface DeltaOutcome {
  node: string;
  requested: number | string; // string for the one string-valued node, material_profile
  applied: number | string | null;
  oldValue: number | string | null;
  status: "APPLIED" | "APPLIED_ADVISORY" | "REJECTED" | "CONFLICT";
  reason?: string;
  cascades?: CascadeEffect[]; // companion changes this SPECIFIC edit triggered, if any
  // carried straight through from the originating ParameterDelta.source (see App.tsx::applyDeltas) —
  // the WS mutate() round trip doesn't (yet) echo back a backend-recomputed source, so this reflects
  // what the proposal itself declared, not a value re-derived post-apply.
  source?: ParamSource | null;
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
  couplingOps?: CouplingOp[];             // AI-proposed load couplings (Phase 2b) — auto-applied
  couplingOpOutcomes?: (CouplingOpOutcome | undefined)[];
  fitOps?: FitOp[];                       // AI-proposed fitted-dimension bindings (2026-07-27) — auto-applied
  fitOpOutcomes?: (FitOpOutcome | undefined)[];
  envelopeOps?: EnvelopeOp[];             // AI-proposed wrap/unwrap/resync of a housing's `wraps` (2026-08-06) — auto-applied
  envelopeOpOutcomes?: (EnvelopeOpOutcome | undefined)[];
  joinAnnotationOps?: JoinAnnotationOp[]; // AI-proposed semantic join annotations (2026-07-27) — auto-applied, never touches geometry
  joinAnnotationOpOutcomes?: (JoinAnnotationOpOutcome | undefined)[];
  regionOps?: RegionOp[];                 // AI-proposed keep-out/keep-in boxes (2026-08-04) — auto-applied, checked by the geometric self-check's "region" issue below
  regionOpOutcomes?: (RegionOpOutcome | undefined)[];
  scopeProposal?: ScopeProposal | null;   // proposed part manifest for a big/ambiguous ask (Phase 5) — display only, no outcomes
  researchFinding?: ResearchFinding | null; // reference research checked before this turn's design (2026-08-01) — display only
  validation?: ValidationResult;          // self-check run after this turn's geometry changes (2026-07-19)
  // The rendered blueprint (GET /blueprint) as a data: URL, captured at self-check time right after a
  // geometry-changing turn (2026-08-05) — shown in the chat UI so the user can visually verify
  // placement/clipping themselves, AND (when the configured model is vision-capable) attached to the
  // NEXT auto-correction turn's outgoing message via chat/buildChatContent.ts, so the same model that
  // placed the parts sees its own render directly. Absent when no self-check ran (e.g. a non-geometry
  // turn) or the blueprint fetch itself failed.
  blueprintImage?: string;
}
