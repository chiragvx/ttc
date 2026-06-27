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

export const SKIN = "domains.structure.skin_thickness_mm";
export const RIB = "domains.structure.internal_rib_spacing_mm";
