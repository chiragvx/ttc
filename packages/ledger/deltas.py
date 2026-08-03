"""The ONLY legal LLM emission.

Inversion #1 made concrete: the geometric agent cannot emit free Python or a safety scalar. Its
entire output surface is a `DeltaProposal` — a list of `ParameterDelta`s (or a request for
clarification). Bound to the API with `tool_choice` forced + `strict:true`, prose and code are
impossible at the wire. The schema enforces SHAPE; the rules validator (separate, not an LLM)
enforces INVARIANTS (bounds clamp, HARD_LOCK, coupled invariants).
"""

from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.ledger.parameter import LockState, ParamSource

# Nodes the LLM may NEVER target — these are grounded-solver outputs. A delta touching one is rejected.
FORBIDDEN_DELTA_PREFIXES: tuple[str, ...] = ("derived.", "review.")

# DeltaProposal's own list-typed fields — see DeltaProposal._repair_known_wire_quirks below (a model
# double-encoding ANY of these as a JSON string is the same failure class as scope_proposal's own
# _coerce_scope_proposal_string coercion, just hitting a sibling list field instead).
_WIRE_REPAIR_LIST_FIELDS: tuple[str, ...] = (
    "deltas", "feature_ops", "instance_ops", "connection_ops", "coupling_ops", "suggestions",
)


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
    # 2026-08-01 (scoped MVP — a single passthrough tag, NOT a confidence-scoring system): where this
    # ONE delta's requested value came from. Fully optional/defaulted so no existing delta payload
    # (persisted event, replayed history, hand-built test fixture) breaks — a missing/"unsourced" tag
    # never blocks or changes acceptance (`packages.ledger.apply.apply_delta` doesn't branch on it at
    # all). Purely descriptive metadata threaded through to `ApplyOutcome.source` for later display.
    source: ParamSource = "unsourced"


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


class FitOp(BaseModel):
    """Wire/unwire/resync a typed FIT BINDING (2026-07-27) — a CONNECTOR's own fitted-dimension
    params derived ONCE from a HOST's cross-section and written as ordinary deltas (never a live,
    never-logged read — see `packages.ledger.schema.FitBinding`'s own docstring for why). The LLM
    WIRES which connector fits which host; it never computes the fitted dimension itself (Inversion
    #1, same posture as `CouplingOp` — the arithmetic lives in `packages.subsystems.fit`, never here).

    For `fit_connector`: `connector_instance` and `host_instance` are REQUIRED. `clearance_mm`
    (signed: positive = clearance/slip fit, negative = interference/press fit) is OPTIONAL — omit it
    only when a JoinAnnotation on the same pair already implies a default; otherwise state it
    explicitly, never guess a physical tolerance. For `resync_fit`: `id` (the existing FitBinding) is
    REQUIRED — re-derives the connector's params against the host's CURRENT state (use this after the
    self-check flags drift, e.g. the host was resized). For `unfit_connector`: `id` is REQUIRED."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["fit_connector", "unfit_connector", "resync_fit"]
    id: Optional[str] = None
    connector_instance: Optional[str] = None
    host_instance: Optional[str] = None
    clearance_mm: Optional[float] = None
    rationale: Optional[str] = None


class JoinAnnotationOp(BaseModel):
    """Add/remove a `JoinAnnotation` (2026-07-27) — records HOW two already-connected parts are
    joined (bolted/press_fit/welded/adhesive/custom), for the BOM/a human assembling the part. Purely
    semantic; never affects geometry (contrast `FitOp`, which does). For `add_join_annotation`:
    `connection_id` (a REAL existing `Connection.id` — the two parts must already be connection_ops-
    mated) and `method` are REQUIRED. `fastener`/`note` are optional free-text display data. For
    `remove_join_annotation`: `id` is REQUIRED."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add_join_annotation", "remove_join_annotation"]
    id: Optional[str] = None
    connection_id: Optional[str] = None
    method: Optional[Literal["bolted", "press_fit", "welded", "adhesive", "custom"]] = None
    fastener: Optional[str] = None
    note: Optional[str] = None
    rationale: Optional[str] = None


class ScopePartProposal(BaseModel):
    """One row of a `ScopeProposal`'s part manifest — a proposed decomposition entry, not an op (no
    apply/outcome; see `ScopeProposal` docstring below). Flat, no nested dicts, same precedent as
    `CouplingInputItem` — `operating_conditions` is a plain list of human-readable strings, not a
    dict, purely for display; nothing downstream parses individual entries in v1."""

    model_config = ConfigDict(extra="forbid")

    subsystem_type: str
    role: str                              # short human label, e.g. "left wing", "battery bay"
    # 2026-07-20 live repro: the model represented a deferred part ("payload bay ring/door — not
    # chosen yet") as a `parts` row with count=0 instead of ScopeProposal.out_of_scope (the field that
    # actually exists for this), and the whole tool call was rejected over it. Widened ge=1 -> ge=0:
    # this is pure display data (see class docstring — "nothing downstream parses individual entries
    # in v1"), so a count=0 row is harmless either way; the prompt section below now also teaches the
    # correct field to use, but the schema shouldn't crash the entire proposal over this either way.
    count: int = Field(default=1, ge=0)
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
    fit_ops: list[FitOp] = Field(
        default_factory=list,
        description="fit_connector: derive a CONNECTOR part's own bore/socket dimensions from a HOST "
                    "part's actual cross-section (e.g. a sleeve's bore from a post's real dia_mm) "
                    "instead of leaving it at a generic default or guessing a number — use this "
                    "whenever a connector-type part needs to physically wrap/grip another specific "
                    "part. resync_fit: re-derive after the host's dimensions changed. Only works "
                    "between a HOST that declares a cross-section and a CONNECTOR that declares a "
                    "matching socket (see the fit catalog below) — not every part pair qualifies")
    join_annotation_ops: list[JoinAnnotationOp] = Field(
        default_factory=list,
        description="record HOW two already-CONNECTED parts are physically joined — bolted, "
                    "press_fit, welded, adhesive, or custom — for the bill of materials. Purely "
                    "semantic/documentation, never affects geometry. Requires the two parts to "
                    "already have a real connection_ops mate (references its id)")
    scope_proposal: Optional[ScopeProposal] = Field(
        default=None,
        description="a structured part-manifest summary for a BIG or AMBIGUOUS multi-part ask ('make "
                    "a drone', 'make a satellite') — additive, NOT a gate: if confident, also emit "
                    "instance_ops in the SAME turn (they still auto-apply immediately, unchanged); if "
                    "genuinely unsure of the decomposition, pair this with request_clarification and "
                    "suggestions instead of instance_ops, and wait for the user's next message")

    @field_validator("scope_proposal", mode="before")
    @classmethod
    def _coerce_scope_proposal_string(cls, v):
        """Tolerate a model double-encoding this field as a JSON string instead of a real nested
        object (2026-07-23 live repro on Qwen: `"scope_proposal": "{\\"goal\\": ...}"` — a whole
        valid ScopeProposal, just wrapped as a string). `scope_proposal` is pure display data (see
        its own docstring/field description — nothing downstream parses it for safety), so parsing
        a model's own over-eager string-encoding here is leniency at the LLM wire boundary, not a
        weakened safety check — a non-string/unparseable value still falls through to normal
        (strict) validation and reports its real error."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v

    @model_validator(mode="before")
    @classmethod
    def _repair_known_wire_quirks(cls, data):
        """Best-effort repair of two independently live-reproduced Qwen3.6-plus tool-call quirks,
        run BEFORE strict per-field validation — liberal at the wire, never at the ledger (mirrors
        `_coerce_scope_proposal_string`'s own framing: nothing here is safety-critical, and anything
        this can't confidently repair falls through to normal strict validation unchanged, reporting
        its real error exactly as before).

        1. **A list field double-encoded as a JSON string** (2026-07-27 live repro: `'deltas': '\\n[{"
        requested_value": 800, ...}]\\n'` instead of a real array) — same failure class as
        `_coerce_scope_proposal_string`, just for `deltas`/`feature_ops`/`instance_ops`/
        `connection_ops`/`coupling_ops`/`suggestions` instead of the single `scope_proposal` object.
        Parsed in place when it decodes to a list; left untouched (falls through to the normal
        "not a valid list" error) on anything else — never masks a genuinely malformed value.

        2. **A dimension field on `add_instance`/`move_instance` itself** instead of a separate
        top-level `deltas` entry (2026-07-27 live repro: an `add_instance` for a `flat_bar` carrying
        `length_mm`/`width_mm`/`thickness_mm` directly on the op, all rejected by InstanceOp's
        extra="forbid"). Recovered ONLY when the extra value is numeric AND the op already names its
        `instance_id` (never guessed) — redirected into a synthesized `ParameterDelta` targeting
        `instances.<instance_id>.params.<key>`, appended to the top-level `deltas` list. Anything
        that doesn't meet both conditions (non-numeric value, or no instance_id to target) is left
        exactly as emitted, so InstanceOp's own extra_forbid still rejects it normally — this never
        silently drops data it can't safely redirect.
        """
        if not isinstance(data, dict):
            return data

        for key in _WIRE_REPAIR_LIST_FIELDS:
            v = data.get(key)
            if isinstance(v, str):
                try:
                    parsed = json.loads(v)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, list):
                    data[key] = parsed

        instance_ops = data.get("instance_ops")
        if isinstance(instance_ops, list):
            known_fields = set(InstanceOp.model_fields.keys())
            recovered: list[dict] = []
            for op in instance_ops:
                if not isinstance(op, dict) or op.get("op") not in ("add_instance", "move_instance"):
                    continue
                instance_id = op.get("instance_id")
                if not instance_id:
                    continue  # can't safely target a delta without a known id — leave op as-is
                for extra_key in [k for k in op if k not in known_fields]:
                    value = op[extra_key]
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        recovered.append({
                            "target_node": f"instances.{instance_id}.params.{extra_key}",
                            "requested_value": value,
                            "rationale": f"recovered from {op['op']}'s own invalid '{extra_key}' field",
                        })
                        del op[extra_key]
                    # else: non-numeric extra — leave it so extra_forbid reports it normally

            if recovered:
                existing = data.get("deltas")
                data["deltas"] = (existing if isinstance(existing, list) else []) + recovered

        return data


def parameter_delta_tool_schema() -> dict:
    """The strict JSON Schema handed to the Claude tool-use API as the delta-emitter's only tool.
    `extra="forbid"` yields `additionalProperties:false`, so the model cannot smuggle extra fields."""
    return DeltaProposal.model_json_schema()


def is_forbidden_target(node: str) -> bool:
    """True if a delta tries to write a grounded-solver / review node the LLM must never originate."""
    return any(node.startswith(p) for p in FORBIDDEN_DELTA_PREFIXES)
