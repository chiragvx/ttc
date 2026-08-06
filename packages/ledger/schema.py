"""The Master Parametric Ledger — the single source of truth for a project's state.

Hardened vs the original PRD schema:
  * `extra="forbid"` on every model (no silent typo-forked state);
  * every tunable node is a `ParameterDef` (uniform lock/bounds);
  * a `derived` section holds SOLVER outputs only — values the LLM is forbidden to write — and they
    are `Optional`, defaulting to None == "unknown" (which blocks export until a real solver fills them);
  * a `review` section carries the human-in-the-loop sign-off state.

Scoped to the WEDGE (functional printable parts). Aerospace domains are deliberately absent — see
the DO-NOT-BUILD cut-list in /CLAUDE.md.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.ledger.parameter import ParameterDef


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectMetadata(_Strict):
    project_id: str
    version_commit: str
    branch: str = "main"
    subsystem_type: str = "bracket"  # key into packages/subsystems/SUBSYSTEM_REGISTRY


class GlobalConstraints(_Strict):
    factor_of_safety_floor: float = Field(default=1.5, ge=1.0, description="export-blocking FS floor")
    # wedge targets are optional; aerospace range/cruise targets intentionally omitted
    max_print_time_seconds: Optional[float] = None
    max_cost_usd: Optional[float] = None  # if set, the Cost discipline blocks export above this


class StructureDomain(_Strict):
    """The structures/material discipline — a small, curated typed block.
    Bracket geometry (plate/skin/rib/hole) has moved to the generic geometry bag; this block now
    carries only cross-cutting discipline data referenced by name in solvers/gates."""

    material_profile: str  # string key resolved against the (versioned) material DB


class ManufacturingDomain(_Strict):
    """The manufacturing/DFM discipline — universal print inputs (any subsystem uses these).
    Per-part geometric features (bolt holes, etc.) live in each subsystem's geometry bag."""

    build_orientation_deg: ParameterDef
    slip_fit_clearance_mm: ParameterDef


class ThermalDomain(_Strict):
    """Thermal discipline inputs (DOMAIN_TAXONOMY.md §3.9). Optional — present only when the part has a
    thermal requirement. operating_temp_c drives a closed-form (L0) material service-temp gate;
    a positive power_dissipation_w requires a grounded (L1) CalculiX heat-transfer margin before export."""

    operating_temp_c: ParameterDef       # environment/service temp the part must survive
    power_dissipation_w: ParameterDef    # heat load from mounted electronics (0 = passive)


class Domains(_Strict):
    """Cross-cutting disciplines. Subsystem geometry lives in `MasterParametricLedger.instances`
    (Phase G) — NOT here. This block only holds the small, curated typed discipline blocks that
    every design references by name (material, universal DFM, thermal)."""

    structure: StructureDomain
    manufacturing: ManufacturingDomain
    thermal: Optional[ThermalDomain] = None


class Transform(_Strict):
    """Relative-to-parent transform for an instance (identity if omitted)."""

    x_mm: float = 0.0
    y_mm: float = 0.0
    z_mm: float = 0.0
    rx_deg: float = 0.0
    ry_deg: float = 0.0
    rz_deg: float = 0.0


class CutFeature(_Strict):
    """A generic subtractive feature (hole/pocket/slot) applied to a HOST instance's own built
    geometry, positioned relative to the host's bounding-box center in the host's local XY frame.

    `depth_mm` is ALWAYS a concrete, positive float here — never an Optional "through" sentinel. A
    later (not-yet-built) stage resolves the conversational notion of "through" to a concrete number
    BEFORE a CutFeature is ever constructed, specifically so the analytic volume path
    (`packages/subsystems/cut_features.py::swept_volume_mm3`) never needs a geometry build to stay
    accurate. `kind` is descriptive only (prompt clarity / tagging) — it does not gate whether the cut
    penetrates; `depth_mm` alone governs that.
    """

    id: str
    kind: Literal["hole", "pocket", "slot"]
    shape: Literal["circle", "rect"]
    dia_mm: Optional[float] = None
    length_mm: Optional[float] = None
    width_mm: Optional[float] = None
    depth_mm: float = Field(gt=0.0)
    x_mm: float = 0.0                  # position relative to the host's own bbox center, local XY
    y_mm: float = 0.0

    @model_validator(mode="after")
    def _check_shape_fields(self) -> "CutFeature":
        if self.shape == "circle" and self.dia_mm is None:
            raise ValueError("CutFeature(shape='circle') requires dia_mm")
        if self.shape == "rect" and (self.length_mm is None or self.width_mm is None):
            raise ValueError("CutFeature(shape='rect') requires length_mm and width_mm")
        # Positivity: depth_mm already gets this from `Field(gt=0.0)`; the shape-conditional footprint
        # fields need the same floor here (a Pydantic `Field(gt=0.0)` on an Optional field only checks
        # values that are present, but a zero/negative footprint is exactly as physically nonsensical
        # as a zero/negative depth -- a hole of diameter 0 or a slot of negative width is not "unknown",
        # it's a malformed cut that must never reach the geometry kernel).
        for name, value in (("dia_mm", self.dia_mm), ("length_mm", self.length_mm), ("width_mm", self.width_mm)):
            if value is not None and value <= 0.0:
                raise ValueError(f"CutFeature.{name} must be > 0 (got {value})")
        return self


class Instance(_Strict):
    """A concrete occurrence of a subsystem in the project's design tree.

    Phase G structural change (2026-07-02): the ledger now holds a TREE of named instances instead
    of a single active subsystem. `ProjectMetadata.subsystem_type` is a compat leftover that mirrors
    the root instance's `subsystem_type`; new code should read `instances[root_id].subsystem_type`.
    A single-part design has exactly one instance (`root_id="root"`, `parent_id=None`); a
    hierarchical design (UAV, robot, machine assembly) has many, related via `parent_id`.
    """

    id: str
    subsystem_type: str            # key into SUBSYSTEM_REGISTRY
    params: dict[str, ParameterDef] = Field(default_factory=dict)
    transform: Optional[Transform] = None
    parent_id: Optional[str] = None   # None == root
    cut_features: list[CutFeature] = Field(default_factory=list)
    # 2026-08-05 (gearbox-housing-generation initiative, Phase 2) -- which instance ids THIS instance
    # (when it's a housing-family subsystem declaring `envelope_socket`, see
    # packages/subsystems/base.py::EnvelopeSocketSpec/Subsystem.envelope_socket) is declared to
    # WRAP/CONTAIN. Same precedent as `cut_features` above: a universal field on every Instance,
    # meaningful only for the subset of subsystems that actually use it -- meaningless/ignored for any
    # subsystem that doesn't declare `envelope_socket` (no housing-family subsystem exists in the
    # catalog yet; a later phase is the first real consumer). Backward compatible: every existing
    # Instance gets an empty list by default, zero behavior change anywhere else in the ledger. Written
    # ONLY through `EnvelopeOp.wrap_group`/`unwrap_group` (packages/ledger/apply.py::
    # apply_envelope_op) -- never derived, never a live-recomputed value itself (contrast `derived.*`,
    # which the LLM can never write at all; `wraps` is ordinary wiring data, the SAME posture
    # `FitBinding.connector_instance`/`host_instance` already have).
    wraps: list[str] = Field(default_factory=list)


class DerivedSafety(_Strict):
    """Outputs of GROUNDED SOLVERS only. The LLM is forbidden to write these (enforced by the gate +
    a future static check). None == "unknown" == blocks export. Never fabricate a value here."""

    factor_of_safety: Optional[float] = None
    mesh_converged: Optional[bool] = None
    min_wall_ok: Optional[bool] = None
    watertight: Optional[bool] = None


class ReviewState(str, Enum):
    AI_PROPOSED = "AI_PROPOSED"
    ENGINEER_REVIEWED = "ENGINEER_REVIEWED"


class Review(_Strict):
    """The human-in-the-loop sign-off FSM. Geometry-class changes start AI_PROPOSED; only an explicit
    engineer accept moves to ENGINEER_REVIEWED. Export requires ENGINEER_REVIEWED."""

    state: ReviewState = ReviewState.AI_PROPOSED
    reviewer: Optional[str] = None


class InterfaceRef(_Strict):
    """A reference to one declared mate point on one instance (Phase 1, 2026-07-19). `interface` names
    an InterfaceSpec on the instance's subsystem (packages/subsystems/base.py)."""

    instance_id: str
    interface: str


class Connection(_Strict):
    """A typed join between two instances' interfaces — the EKG 'connection' made a first-class ledger
    object (ENGINEERING_GRAPH_ARCHITECTURE.md §1). Replaces hand-computed placement: mating `a` to `b`
    means the placement solver (packages/subsystems/placement.py) positions the not-yet-placed part so
    its interface frame coincides with its partner's, instead of the LLM computing a Transform.

    `kind` is advisory today (all kinds mate the same way in Phase 1); `containment` is the edge that
    dissolves body-vs-frame (arch doc §5). `gap_mm` pushes the two apart along the mate normal."""

    id: str
    a: InterfaceRef
    b: InterfaceRef
    kind: Literal["mate", "bolted", "slip_fit", "containment"] = "mate"
    gap_mm: float = 0.0


class JoinAnnotation(_Strict):
    """Semantic-only (2026-07-27, ENGINEERING_GRAPH_ARCHITECTURE.md follow-on): records HOW two
    already-connected parts are actually joined in the real world — bolted, press-fit, welded,
    adhesive, or a custom method prose can't be reduced to one of those. Attached to an EXISTING
    `Connection` by `connection_id` (never a standalone record of "these two parts touch" — that fact
    already lives on `Connection` itself; duplicating it here would create two records of one
    physical joint that can silently diverge).

    Deliberately NOT geometry-touching — this is BOM/documentation-grade data (what a technician
    reads to actually assemble the part), never a source of any dimension. Contrast with `FitBinding`
    (construction-grade: derives an actual manufactured dimension). The two are related but distinct:
    `fit_connector` (packages/ledger/apply.py) may READ a JoinAnnotation on the same pair to pick a
    sensible default `clearance_mm` (press_fit -> tight/negative, bolted -> a small positive
    clearance, welded -> zero) — but `FitBinding` never stores its own copy of `method`; there is
    exactly one place a join's semantic classification lives.

    `fastener`/`note` are free-text display data (mirrors `CouplingInput.rationale`'s own "nothing
    downstream parses this, it's for a human reading the BOM" precedent) — never parsed, never
    safety-relevant, so a typo or an unusual value can never break anything downstream."""

    id: str
    connection_id: str
    method: Literal["bolted", "press_fit", "welded", "adhesive", "custom"]
    fastener: Optional[str] = None   # e.g. "M5x16 socket cap" -- display only
    note: Optional[str] = None       # free text, required in spirit for method="custom"


class CouplingInput(_Strict):
    """One input to a coupling's relation (Phase 2, 2026-07-19): EITHER a literal stated value (a duty
    condition — g-load, operating pressure), OR sourced from a part's own param (`from_instance` +
    `from_param`). Exactly one form, enforced below. The LLM sets these; it never writes the relation
    math (Inversion #1 — see packages/couplings/relations.py)."""

    value: Optional[float] = None
    from_instance: Optional[str] = None
    from_param: Optional[str] = None

    @model_validator(mode="after")
    def _one_form(self) -> "CouplingInput":
        literal = self.value is not None
        sourced = self.from_instance is not None and self.from_param is not None
        if literal == sourced:  # neither, or both
            raise ValueError("CouplingInput must be EITHER a literal `value` OR a "
                             "`from_instance`+`from_param` source, not both/neither")
        return self


class Coupling(_Strict):
    """A typed edge that DERIVES a load on `target_instance` from a registered deterministic relation
    (Phase 2 — ENGINEERING_GRAPH_ARCHITECTURE.md §2). The load stops being a stated scalar and becomes
    a graph output: change a source part/param -> the relation re-runs -> the target's load updates ->
    its grounding re-flags (the pump's "casing pressure change cracked the crank" behaviour).

    `relation` names a registered relation (packages/couplings/relations.py); `inputs` map the
    relation's declared input quantities to `CouplingInput`s. The LLM WIRES this; it never authors the
    physics — a relation not in the registry makes the target's load `"unknown"`, which blocks the
    green light rather than fabricating one.

    `target_param` (2026-08-04, generic coupling read path) is OPTIONAL and defaults to `None` —
    byte-identical to today's behavior on every existing coupling, which never sets it. When set, it
    names which of `target_instance`'s OWN params this coupling's resolved value corresponds to, for
    DISPLAY / self-check purposes ONLY (e.g. a gear-ratio self-check comparing a computed ratio against
    what's actually stored on the driven gear). It is a read-only annotation — nothing in this codebase
    ever writes a coupling's resolved value into that param (that would silently overwrite a param a
    user or a prior delta set, exactly what Inversion #1 forbids); see
    `packages/couplings/resolve.py::derived_param_value`, the one (additive, read-only) consumer."""

    id: str
    target_instance: str
    relation: str
    inputs: dict[str, CouplingInput] = Field(default_factory=dict)
    target_param: Optional[str] = None


class FitInput(_Strict):
    """One dimension role in a fit: which of the HOST's own params supplies the value, and which of
    the CONNECTOR's own params receives the computed (host value + clearance) result. Round hosts
    have one FitInput (dia); rect hosts have two (width, height)."""

    host_param: str
    connector_param: str


class FitBinding(_Strict):
    """A typed edge (2026-07-27, ENGINEERING_GRAPH_ARCHITECTURE.md follow-on): CONNECTOR's fitted
    geometry params are DERIVED from HOST's own resolved cross-section, computed ONCE at wire time
    and written through the ordinary ParameterDelta path (packages/ledger/apply.py::apply_delta) --
    never a live-recomputed, never-logged value (see packages/couplings/resolve.py's Coupling, which
    IS live-recomputed but deliberately never touches `params`; a connector's bore is geometry, not a
    safety scalar, so it stays on the ParameterDef-set-by-delta side of that line).

    This is the wiring FACT, event-sourced like Coupling itself -- the resolved dimension lives in
    the connector's own `params` (an ordinary, auditable ParameterDef), not here. `fit_gate_findings`
    (packages/transport/app.py) re-derives what compute_fit WOULD produce today and compares it
    against what's actually stored, to catch drift after the host resizes -- this record is what that
    check re-verifies against, not a cache of the number itself.

    `kind` mirrors FitProfile/FitSocketSpec's own kind ("round" | "rect") -- both sides must agree,
    checked at wire time (packages/ledger/apply.py::apply_fit_op), never inferred here.
    `clearance_mm` is signed: positive = clearance/slip fit, negative = interference/press fit. No
    `join_kind` field on purpose -- a JoinAnnotation (when built) is read ONCE at wire time to pick a
    clearance default; FitBinding never keeps a second, potentially-diverging copy of that label."""

    id: str
    connector_instance: str
    host_instance: str
    kind: Literal["round", "rect"]
    inputs: list[FitInput]
    clearance_mm: float = 0.0


class Region(_Strict):
    """A named keep-out/keep-in box on a HOST instance's own local frame (2026-08-04,
    ENGINEERING_GRAPH_ARCHITECTURE.md follow-on) — e.g. "gear_train_clearance" or a sensor's optical
    cone. Pure geometric ANNOTATION: it records WHERE a volume of interest is; it derives nothing and
    nothing derives it (contrast `Coupling`, which derives a load, or `FitBinding`, which derives a
    dimension). `kind="keep_out"` means nothing else may occupy this box; `kind="keep_in"` means
    everything relevant must stay INSIDE it.

    Per this session's keepout_mm lesson (packages/subsystems/base.py's existing, zero-adopter keepout
    mechanism is the cautionary example): this record alone is NOT a consumer — a caller that adds
    Regions must also be the one wiring an actual interference/containment check against them, or this
    is dead plumbing exactly like keepout_mm.

    `x_mm`/`y_mm`/`z_mm` are the box's CENTER; `dx_mm`/`dy_mm`/`dz_mm` are its full extents (not
    half-extents) — both in the host's own local frame, the SAME convention as `CutFeature`'s
    x_mm/y_mm. Extents must be strictly positive (a zero/negative box is not "unknown", it's
    malformed) — enforced here AND re-checked at apply time (packages/ledger/apply.py::apply_region_op)
    for a clean REJECTED message rather than a raw ValidationError."""

    id: str
    host_instance: str
    kind: Literal["keep_out", "keep_in"]
    label: str          # human/LLM-given purpose, e.g. "gear_train_clearance"
    x_mm: float
    y_mm: float
    z_mm: float
    dx_mm: float = Field(gt=0.0)
    dy_mm: float = Field(gt=0.0)
    dz_mm: float = Field(gt=0.0)


class MasterParametricLedger(_Strict):
    project_metadata: ProjectMetadata
    global_constraints: GlobalConstraints = Field(default_factory=GlobalConstraints)
    domains: Domains
    # Phase G — the design tree. A single-part design has one instance (id="root", parent_id=None).
    # A hierarchical design (UAV, robot) has many, related via parent_id. Empty by default during the
    # migration; app code seeds a root instance from the active subsystem.
    instances: dict[str, Instance] = Field(default_factory=dict)
    root_id: str = "root"
    # Phase 1 (2026-07-19) — typed interface-to-interface joins. A part with a connection is placed by
    # the mate solver, not by a hand-set transform (which still works as a fallback/override). Empty
    # for every design that predates this — fully backward-compatible.
    connections: list[Connection] = Field(default_factory=list)
    # 2026-07-27 -- semantic HOW-joined data attached to a Connection (bolted/press_fit/welded/...).
    # BOM/documentation-grade only, never geometry-touching. See JoinAnnotation's own docstring.
    join_annotations: list[JoinAnnotation] = Field(default_factory=list)
    # Phase 2 (2026-07-19) — typed load couplings: a target's load DERIVED from a registered relation
    # over source parts/duty, instead of a stated scalar. Empty for every pre-Phase-2 design.
    couplings: list[Coupling] = Field(default_factory=list)
    # 2026-07-27 -- typed fit edges: a connector's own params derived ONCE from a host's cross-section
    # and written as ordinary deltas (see FitBinding's own docstring). Empty for every pre-existing design.
    fit_bindings: list[FitBinding] = Field(default_factory=list)
    # 2026-08-04 -- named keep-out/keep-in volumes on a host instance (see Region's own docstring).
    # Pure geometric annotation, empty for every pre-existing design.
    regions: list[Region] = Field(default_factory=list)
    derived: DerivedSafety = Field(default_factory=DerivedSafety)
    review: Review = Field(default_factory=Review)
