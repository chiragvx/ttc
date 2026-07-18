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
    derived: DerivedSafety = Field(default_factory=DerivedSafety)
    review: Review = Field(default_factory=Review)
