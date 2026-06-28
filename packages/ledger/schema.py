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
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.ledger.parameter import ParameterDef


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectMetadata(_Strict):
    project_id: str
    version_commit: str
    branch: str = "main"


class GlobalConstraints(_Strict):
    factor_of_safety_floor: float = Field(default=1.5, ge=1.0, description="export-blocking FS floor")
    # wedge targets are optional; aerospace range/cruise targets intentionally omitted
    max_print_time_seconds: Optional[float] = None


class StructureDomain(_Strict):
    material_profile: str  # string key resolved against the (versioned) material DB; see external-dataset gap
    skin_thickness_mm: ParameterDef
    internal_rib_spacing_mm: ParameterDef


class ManufacturingDomain(_Strict):
    # supportless overhang is a constraint relative to a build direction the ledger MUST carry
    build_orientation_deg: ParameterDef
    slip_fit_clearance_mm: ParameterDef
    # bolt-hole diameter: a real designable feature (changes the FEA stress field -> a geometry param).
    # The hole COUNT is deliberately NOT tunable here — it is topology-changing (the OCAF identity wall).
    hole_diameter_mm: ParameterDef


class Domains(_Strict):
    structure: StructureDomain
    manufacturing: ManufacturingDomain


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


class MasterParametricLedger(_Strict):
    project_metadata: ProjectMetadata
    global_constraints: GlobalConstraints = Field(default_factory=GlobalConstraints)
    domains: Domains
    derived: DerivedSafety = Field(default_factory=DerivedSafety)
    review: Review = Field(default_factory=Review)
