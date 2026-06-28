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
}

export interface MutationApplied {
  node: string;
  value: number;
  old_value?: number | null; // pre-change value, for Undo
  status: string; // APPLIED | CLAMPED
}

export interface CascadeUpdate {
  event_type: "PARAMETER_CASCADE_UPDATE";
  mutations_applied: MutationApplied[];
  telemetry_delta: TelemetryDelta;
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

// --- chat (SSE) ---
export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "proposal"; deltas: ParameterDelta[]; clarification: string | null; suggestions: string[] }
  | { type: "no_llm" }
  | { type: "error"; message: string }
  | { type: "done" };

export interface DeltaOutcome {
  node: string;
  requested: number;
  applied: number | null;
  oldValue: number | null;
  status: "APPLIED" | "CLAMPED" | "REJECTED" | "CONFLICT";
  reason?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  clarification?: string | null;
  suggestions?: string[];
  outcomes?: DeltaOutcome[];
}

export const SKIN = "domains.structure.skin_thickness_mm";
export const RIB = "domains.structure.internal_rib_spacing_mm";
export const HOLE_DIA = "domains.manufacturing.hole_diameter_mm";
