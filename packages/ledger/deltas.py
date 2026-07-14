"""The ONLY legal LLM emission.

Inversion #1 made concrete: the geometric agent cannot emit free Python or a safety scalar. Its
entire output surface is a `DeltaProposal` — a list of `ParameterDelta`s (or a request for
clarification). Bound to the API with `tool_choice` forced + `strict:true`, prose and code are
impossible at the wire. The schema enforces SHAPE; the rules validator (separate, not an LLM)
enforces INVARIANTS (bounds clamp, HARD_LOCK, coupled invariants).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.ledger.parameter import LockState

# Nodes the LLM may NEVER target — these are grounded-solver outputs. A delta touching one is rejected.
FORBIDDEN_DELTA_PREFIXES: tuple[str, ...] = ("derived.", "review.")


class ParameterDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_node: str = Field(description="dotted ledger path, e.g. 'instances.root.params.skin_thickness_mm'")
    requested_value: float
    set_lock: Optional[LockState] = None
    rationale: Optional[str] = None


class FeatureOp(BaseModel):
    """Add/update/remove a hole/pocket/slot cut (`packages/ledger/schema.py::CutFeature`) on any
    instance. Same precedent as `InstanceOp` below: a new field on `DeltaProposal`, not a second
    tool — the LLM's entire output surface stays the one forced tool call."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add_feature", "update_feature", "remove_feature"]
    instance_id: str
    kind: Optional[Literal["hole", "pocket", "slot"]] = None   # required for add/update
    shape: Optional[Literal["circle", "rect"]] = None          # required for add/update
    dia_mm: Optional[float] = None
    length_mm: Optional[float] = None
    width_mm: Optional[float] = None
    through: bool = False        # convenience: LLM says "cut all the way through" instead of a number
    depth_mm: Optional[float] = None   # explicit partial depth; ignored if through=True
    x_mm: float = 0.0
    y_mm: float = 0.0
    feature_id: Optional[str] = None   # required for update_feature/remove_feature (which existing
                                        # CutFeature.id to target); for add_feature, THIS FUNCTION (not
                                        # the LLM) generates a fresh id — the LLM never invents ids for
                                        # add, only references them for update/remove after having seen
                                        # them echoed back in a prior turn's applied-delta outcome
    rationale: Optional[str] = None


class InstanceOp(BaseModel):
    """Add/remove/move an instance of an EXISTING, already-registered subsystem type, to compose a
    multi-part assembly (a satellite, a drone frame, a robot arm, ...) out of catalog building
    blocks. The SAME precedent as `FeatureOp`: a new field on `DeltaProposal`, not a second tool.

    This package has no subsystem registry knowledge (`packages/ledger/CLAUDE.md`: "No OCCT, no
    solver, no LLM, no I/O, no subsystems" purity) — `subsystem_type` is validated at APPLY time
    against an injected `known_subsystem_types` set, not here. The LLM must never invent a new part
    type; it may only compose types that already exist in the catalog.

    `move_instance` reuses the SAME fields as `add_instance`/`remove_instance` above — no new fields
    needed. For `move_instance`:
      - `instance_id` is REQUIRED: the id of the ALREADY-PLACED instance to reposition (a REAL
        existing id, never invented — see `packages.ledger.apply.apply_instance_op`).
      - `x_mm`/`y_mm`/`z_mm` are REQUIRED, ALL THREE TOGETHER. Unlike `add_instance` (where omitting
        all three means "let auto-layout place it"), there is no sensible auto-layout fallback for an
        explicit move request — the caller asked to move it somewhere specific, so all three axes
        must be given.
      - `rx_deg`/`ry_deg`/`rz_deg` remain OPTIONAL, all-or-nothing (same convention as
        `add_instance`). If omitted, the instance KEEPS ITS CURRENT rotation — it is NOT reset to 0.
        This differs from `add_instance`, where a fresh instance has no "current" rotation to
        preserve; an existing instance being moved has a real current rotation that must not be
        silently zeroed just because the caller only wanted to change position.
    """

    model_config = ConfigDict(extra="forbid")

    op: Literal["add_instance", "remove_instance", "move_instance"]
    subsystem_type: Optional[str] = None   # required for add_instance; must be a REAL registered name
    instance_id: Optional[str] = None      # required for remove_instance/move_instance; optional for
                                            # add_instance (auto-generated if omitted, mirroring
                                            # POST /instances' existing "{subsystem_type}_{n}" scheme)
    parent_id: Optional[str] = None        # omitted -> top-level part; unknown id -> falls back to
                                            # top-level rather than rejecting the add (see
                                            # packages.ledger.apply.resolve_instance_parent)
    x_mm: Optional[float] = None           # explicit position (all-or-nothing with y_mm/z_mm — if the
    y_mm: Optional[float] = None           # LLM wants intentional placement, e.g. "stack on top of the
    z_mm: Optional[float] = None           # enclosure"); if all three are None, no Transform is set and
                                            # the EXISTING auto-layout in instance_world_offsets handles
                                            # spacing automatically — this is the expected common case
                                            # for add_instance. For move_instance, all three are REQUIRED
                                            # (no auto-layout fallback for an explicit move — see above).
    rx_deg: Optional[float] = None         # explicit rotation (all-or-nothing with ry_deg/rz_deg, same
    ry_deg: Optional[float] = None         # convention as x_mm/y_mm/z_mm) — e.g. orienting a longeron's
    rz_deg: Optional[float] = None         # local length axis along a different global axis. For
                                            # add_instance, rotation may ONLY be given together with an
                                            # explicit position (all of x_mm/y_mm/z_mm also given):
                                            # auto-layout computes a position from the part's UNROTATED
                                            # bounding box, so it has no way to place a rotated part
                                            # correctly — rotation without an explicit position is
                                            # rejected at apply time. For move_instance, rotation is
                                            # optional and omitting it preserves the instance's CURRENT
                                            # rotation (see class docstring above).
    rationale: Optional[str] = None


class DeltaProposal(BaseModel):
    """What the geometric agent returns. Either deltas to apply, or a clarification request when the
    natural-language intent is ambiguous (e.g. '6S', '2 inch', 'make it stronger'). Asking is a
    first-class, rewarded behavior — not a failure."""

    model_config = ConfigDict(extra="forbid")

    deltas: list[ParameterDelta] = Field(default_factory=list)
    request_clarification: Optional[str] = None
    suggestions: list[str] = Field(default_factory=list,
                                   description="quick-reply options to offer with a clarification")
    feature_ops: list[FeatureOp] = Field(
        default_factory=list,
        description="add/update/remove a hole/pocket/slot cut on any instance — use this instead of "
                    "claiming a part type can't have a cutout")
    instance_ops: list[InstanceOp] = Field(
        default_factory=list,
        description="add/remove/move an instance of an EXISTING part type to compose a multi-part "
                    "assembly — use add_instance when the user asks for something that isn't a single "
                    "catalog part type (a satellite, a drone frame, a robot arm, ...): decompose it "
                    "into several EXISTING subsystem types instead of refusing. Use move_instance to "
                    "reposition an ALREADY-PLACED instance (e.g. 'put the pod on top of the wing')")


def parameter_delta_tool_schema() -> dict:
    """The strict JSON Schema handed to the Claude tool-use API as the delta-emitter's only tool.
    `extra="forbid"` yields `additionalProperties:false`, so the model cannot smuggle extra fields."""
    return DeltaProposal.model_json_schema()


def is_forbidden_target(node: str) -> bool:
    """True if a delta tries to write a grounded-solver / review node the LLM must never originate."""
    return any(node.startswith(p) for p in FORBIDDEN_DELTA_PREFIXES)
