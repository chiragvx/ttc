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
    # 2026-07-19 — widened from a bare float: domains.structure.material_profile is a real, LLM-settable
    # design choice but a bare str, not a ParameterDef (no bounds/lock to number). It's the ONLY string
    # target_node that exists (see apply.py::apply_delta's string branch) — every other string field in
    # the schema (ids, Instance.subsystem_type, connection/coupling refs) already has its own dedicated
    # op type (InstanceOp/ConnectionOp/CouplingOp), never this one.
    requested_value: float | str
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


class ConnectionOp(BaseModel):
    """Add/remove a typed JOIN between two instances' declared interfaces (Phase 1b, 2026-07-19) — the
    SAME precedent as `FeatureOp`/`InstanceOp`: a new field on `DeltaProposal`, not a second tool. This
    is how the copilot MATES parts instead of hand-computing a Transform: it wires
    `wing_left.root <-> bwb_fuselage.tip_left` and the placement solver
    (packages/subsystems/placement.py) derives the position from the parts' declared frames.

    For `add_connection`: `a_instance`/`a_interface`/`b_instance`/`b_interface` are REQUIRED and each
    interface must be one this part's subsystem actually DECLARES (validated at apply time against the
    registry — the LLM must never invent an interface name, only use ones listed in the part-types
    menu). `id` is optional (auto-generated if omitted, like add_instance). `kind`/`gap_mm` are
    optional. For `remove_connection`: `id` is REQUIRED (a real existing connection id)."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add_connection", "remove_connection"]
    id: Optional[str] = None                # required for remove_connection; auto-generated for add
    a_instance: Optional[str] = None        # required for add_connection: first part's instance id
    a_interface: Optional[str] = None       # required for add_connection: a declared interface on it
    b_instance: Optional[str] = None        # required for add_connection: second part's instance id
    b_interface: Optional[str] = None       # required for add_connection: a declared interface on it
    kind: Optional[Literal["mate", "bolted", "slip_fit", "containment"]] = None
    gap_mm: Optional[float] = None
    rationale: Optional[str] = None


class CouplingInputItem(BaseModel):
    """One named input wired for a CouplingOp's relation — a LIST item (not a dict) so the tool-use
    JSON schema stays flat, matching every other Op in this file. `name` must be one of the relation's
    declared input quantity names (packages/couplings/relations.py::Relation.inputs)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: Optional[float] = None
    from_instance: Optional[str] = None
    from_param: Optional[str] = None
    # 2026-07-19 — live failure: the model tried to explain EACH input separately ("battery mass: 3kg",
    # "8g launch accel") and got REJECTED wholesale by extra="forbid" since only CouplingOp itself (not
    # its individual inputs) had a rationale slot. Never read anywhere (same as ParameterDelta.rationale
    # and CouplingOp.rationale below — grep confirms zero readers in packages/ledger or packages/transport)
    # — purely a legal place for the LLM to put its per-input reasoning instead of crashing the whole
    # tool call trying to smuggle it into a field that doesn't exist.
    rationale: Optional[str] = None


class CouplingOp(BaseModel):
    """Add/remove a typed LOAD COUPLING (Phase 2b, 2026-07-19) — the LLM WIRES a relation by name
    (packages/couplings/relations.py), it never authors the physics (Inversion #1). For add_coupling:
    `target_instance`, `relation`, and `inputs` (ALL of the relation's declared inputs, by name) are
    REQUIRED — an incomplete wiring is rejected at apply time with the relation's full input list,
    rather than silently creating a coupling doomed to resolve "unknown" forever. For remove_coupling:
    `id` is REQUIRED."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add_coupling", "remove_coupling"]
    id: Optional[str] = None
    target_instance: Optional[str] = None
    relation: Optional[str] = None
    inputs: list[CouplingInputItem] = Field(default_factory=list)
    rationale: Optional[str] = None


class ScopePartProposal(BaseModel):
    """One row of a `ScopeProposal`'s part manifest — a proposed decomposition entry, not an op (no
    apply/outcome; see `ScopeProposal` docstring below). Flat, no nested dicts, same precedent as
    `CouplingInputItem` — `operating_conditions` is a plain list of human-readable strings, not a
    dict, purely for display; nothing downstream parses individual entries in v1."""

    model_config = ConfigDict(extra="forbid")

    subsystem_type: str
    role: str                              # short human label, e.g. "left wing", "battery bay"
    count: int = Field(default=1, ge=1)
    operating_conditions: list[str] = Field(default_factory=list)
    rationale: Optional[str] = None


class ScopeProposal(BaseModel):
    """A structured part-manifest SUMMARY for a big/ambiguous multi-part ask ('make a drone', 'make a
    satellite') — pure DISPLAY data, unlike `FeatureOp`/`InstanceOp`/`ConnectionOp`/`CouplingOp`: it
    has no `op`, no REST endpoint, no APPLIED/REJECTED outcome, nothing to apply. It is ADDITIVE, not
    a gate (packages/agents/CLAUDE.md's 2026-07-04 policy is unchanged: a proposal auto-applies the
    instant it arrives; Undo is the safety net, not a pre-apply confirmation click). See
    `DeltaProposal.scope_proposal`'s field description for exactly how it pairs with `instance_ops`
    (confident case) vs. `request_clarification`+`suggestions` (genuinely unsure case)."""

    model_config = ConfigDict(extra="forbid")

    goal: str                              # echoes the stated intent back
    parts: list[ScopePartProposal] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


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
    connection_ops: list[ConnectionOp] = Field(
        default_factory=list,
        description="MATE two parts by wiring their declared interfaces (e.g. wing_left.root <-> "
                    "bwb_fuselage.tip_left) instead of hand-computing a position — the engine derives "
                    "the placement from the parts' own frames. PREFER this over computing x/y/z for a "
                    "part that has a matching interface on its host")
    coupling_ops: list[CouplingOp] = Field(
        default_factory=list,
        description="wire a load onto a part FROM another part's condition via a registered relation "
                    "(e.g. force_from_pressure_area) instead of stating a load scalar — use this when "
                    "the load is CAUSED by another part, not a stated duty condition")
    scope_proposal: Optional[ScopeProposal] = Field(
        default=None,
        description="a structured part-manifest summary for a BIG or AMBIGUOUS multi-part ask ('make "
                    "a drone', 'make a satellite') — additive, NOT a gate: if confident, also emit "
                    "instance_ops in the SAME turn (they still auto-apply immediately, unchanged); if "
                    "genuinely unsure of the decomposition, pair this with request_clarification and "
                    "suggestions instead of instance_ops, and wait for the user's next message")


def parameter_delta_tool_schema() -> dict:
    """The strict JSON Schema handed to the Claude tool-use API as the delta-emitter's only tool.
    `extra="forbid"` yields `additionalProperties:false`, so the model cannot smuggle extra fields."""
    return DeltaProposal.model_json_schema()


def is_forbidden_target(node: str) -> bool:
    """True if a delta tries to write a grounded-solver / review node the LLM must never originate."""
    return any(node.startswith(p) for p in FORBIDDEN_DELTA_PREFIXES)
