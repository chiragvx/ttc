"""The two-plane WebSocket protocol — typed wire messages.

Adds what the original PRD's contract lacked: a NACK/rejection message (what the server sends when a
mutation violates the FS floor / a HARD_LOCK / bounds), and an explicit three-tier message taxonomy
so the honest clock separation is visible on the wire. Tiers 1/2 (kernel regen, solver) are declared
here; this app implements Tier 0 (mutation -> validated cascade + analytic telemetry) fully.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- client -> server -------------------------------------------------------
class ParamMutationRequest(_Msg):
    event_type: Literal["PARAMETER_MUTATION_REQUEST"] = "PARAMETER_MUTATION_REQUEST"
    target_node: str
    requested_value: float
    set_lock: Optional[str] = None


# ---- server -> client -------------------------------------------------------
class TelemetryDelta(_Msg):
    total_mass_g: float
    cg_mm: tuple[float, float, float]
    estimated_print_time_s: float


class MutationApplied(_Msg):
    node: str
    value: float
    status: str  # APPLIED | CLAMPED


class CascadeUpdate(_Msg):
    """Tier 0 response: rules-validated mutation + analytic telemetry (no kernel/solver in this path)."""
    event_type: Literal["PARAMETER_CASCADE_UPDATE"] = "PARAMETER_CASCADE_UPDATE"
    mutations_applied: list[MutationApplied]
    telemetry_delta: TelemetryDelta


class MutationRejected(_Msg):
    """The NACK the PRD lacked: a mutation that violates a rule never silently no-ops."""
    event_type: Literal["PARAMETER_MUTATION_REJECTED"] = "PARAMETER_MUTATION_REJECTED"
    target_node: str
    status: str   # REJECTED | CONFLICT
    reason: str


# Tier 1/2 message names (declared for the protocol; executed by the kernel/solver planes, not Tier 0)
KERNEL_REGEN_COMPLETE = "KERNEL_REGEN_COMPLETE"
SOLVER_RESULT = "SOLVER_RESULT"
