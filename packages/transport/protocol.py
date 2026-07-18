"""The two-plane WebSocket protocol — typed wire messages.

Adds what the original PRD's contract lacked: a NACK/rejection message (what the server sends when a
mutation violates the FS floor / a HARD_LOCK / bounds), and an explicit three-tier message taxonomy
so the honest clock separation is visible on the wire. Tiers 1/2 (kernel regen, solver) are declared
here; this app implements Tier 0 (mutation -> validated cascade + analytic telemetry) fully.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    estimated_cost_usd: float   # analytic — the Cost discipline readout


class MutationApplied(_Msg):
    node: str
    value: float
    old_value: Optional[float] = None  # pre-change value, so the client can Undo
    status: str  # APPLIED | APPLIED_ADVISORY


class CascadeEffect(_Msg):
    """A companion change a subsystem's deterministic CascadeRule made as a side effect of the
    direct edit (prd-27-8.14/prd4.md §2.2's `cascades_applied` — e.g. growing a bolt hole cascades
    the plate depth up to keep the edge-distance rule satisfied, instead of the request being
    rejected outright). Never LLM-originated — packages/ledger/apply.py::CascadeRule is a plain
    deterministic function the active subsystem declares."""
    node: str
    value: float
    old_value: Optional[float] = None
    reason: str


class ValidRange(_Msg):
    """The PHYSICALLY-VALID slider range for one geometry param, given every OTHER param's current
    value (2026-07-19). Pure closed-form from the subsystem's own cross-field invariants
    (packages/subsystems/valid_ranges.py) -- NOT the advisory recommended `bounds` (those stay a soft
    envelope the copilot may exceed; see parameter.py). The frontend hard-clamps a slider to
    [valid_min, valid_max] so a human drag can never reach a CONFLICT (e.g. blend_taper_mm past
    span_mm/2). Rides on every Tier-0 mutation response so all sliders' clamps stay live as other
    params change -- microsecond-cheap, no kernel/solver."""
    node: str
    valid_min: float
    valid_max: float


class CascadeUpdate(_Msg):
    """Tier 0 response: rules-validated mutation + analytic telemetry (no kernel/solver in this path)."""
    event_type: Literal["PARAMETER_CASCADE_UPDATE"] = "PARAMETER_CASCADE_UPDATE"
    mutations_applied: list[MutationApplied]
    cascades_applied: list[CascadeEffect] = Field(default_factory=list)
    telemetry_delta: TelemetryDelta
    # Refreshed slider clamps for EVERY geometry param of the active instance (not just the mutated
    # one — changing span_mm shifts blend_taper_mm's own valid max, so all must refresh together).
    # Empty when the active instance has no geometry params / no registered model. See ValidRange.
    valid_ranges: list[ValidRange] = Field(default_factory=list)


class MutationRejected(_Msg):
    """The NACK the PRD lacked: a mutation that violates a rule never silently no-ops."""
    event_type: Literal["PARAMETER_MUTATION_REJECTED"] = "PARAMETER_MUTATION_REJECTED"
    target_node: str
    status: str   # REJECTED | CONFLICT
    reason: str


# Tier 1/2 message names (declared for the protocol; executed by the kernel/solver planes, not Tier 0)
KERNEL_REGEN_COMPLETE = "KERNEL_REGEN_COMPLETE"
SOLVER_RESULT = "SOLVER_RESULT"
