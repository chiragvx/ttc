"""Acceptance tests for Inversion #1: a missing grounded result is "unknown" and BLOCKS export;
HARD_LOCK is immune to the automated path; the FS floor and human sign-off are enforced.

These are pure-Python (no kernel/solver/LLM) and must stay green from day one. They are the
executable form of the safety contract.
"""

from __future__ import annotations

import pytest

from packages.ledger.deltas import is_forbidden_target
from packages.ledger.gates import ExportStatus, evaluate_export_gates
from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import (
    Domains,
    GlobalConstraints,
    Instance,
    ManufacturingDomain,
    MasterParametricLedger,
    ProjectMetadata,
    Review,
    ReviewState,
    StructureDomain,
)


def _pd(value: float, lo: float, hi: float, lock: LockState = LockState.DYNAMIC) -> ParameterDef:
    return ParameterDef(value=value, unit="mm", bounds=(lo, hi), lock_state=lock)


def _ledger(**overrides) -> MasterParametricLedger:
    params = {
        "skin_thickness_mm":       _pd(2.0, 1.0, 5.0),
        "internal_rib_spacing_mm": _pd(20.0, 10.0, 50.0),
        "plate_width_mm":          _pd(60.0, 40.0, 120.0),
        "plate_depth_mm":          _pd(40.0, 30.0, 80.0),
        "hole_diameter_mm":        _pd(6.0, 3.0, 10.0),
    }
    root = Instance(id="root", subsystem_type="bracket", params=params, parent_id=None)
    base = MasterParametricLedger(
        project_metadata=ProjectMetadata(project_id="p1", version_commit="v0", branch="main"),
        global_constraints=GlobalConstraints(factor_of_safety_floor=1.5),
        domains=Domains(
            structure=StructureDomain(material_profile="PLA"),
            manufacturing=ManufacturingDomain(
                build_orientation_deg=_pd(0.0, 0.0, 90.0),
                slip_fit_clearance_mm=_pd(0.2, 0.0, 1.0),
            ),
        ),
        instances={"root": root},
        root_id="root",
    )
    return base.model_copy(update=overrides)


def _fully_passing_ledger() -> MasterParametricLedger:
    led = _ledger()
    led.derived.factor_of_safety = 2.0
    led.derived.mesh_converged = True
    led.derived.watertight = True
    led.derived.min_wall_ok = True
    led.review = Review(state=ReviewState.ENGINEER_REVIEWED, reviewer="pe@example.com")
    return led


def test_missing_fs_blocks_export_as_unknown():
    """The core inversion: no grounded FS -> 'unknown' -> EXPORT_BLOCKED. Never a fabricated pass."""
    result = evaluate_export_gates(_ledger())  # derived.* all None by default
    assert result.status is ExportStatus.EXPORT_BLOCKED
    assert "factor_of_safety" in result.unknowns


def test_fully_grounded_and_reviewed_ledger_is_eligible():
    result = evaluate_export_gates(_fully_passing_ledger())
    assert result.eligible, result.reasons


def test_fs_below_floor_blocks():
    led = _fully_passing_ledger()
    led.derived.factor_of_safety = 1.2
    result = evaluate_export_gates(led)
    assert result.status is ExportStatus.EXPORT_BLOCKED
    assert any("below floor" in r for r in result.reasons)


def test_export_requires_human_signoff():
    led = _fully_passing_ledger()
    led.review = Review(state=ReviewState.AI_PROPOSED)
    result = evaluate_export_gates(led)
    assert result.status is ExportStatus.EXPORT_BLOCKED
    assert any("sign-off" in r for r in result.reasons)


def test_hard_lock_parameter_cannot_be_moved_by_automated_path():
    locked = _pd(4.5, 3.0, 6.0, lock=LockState.HARD_LOCK)
    with pytest.raises(ValueError):
        locked.with_value(5.0)


def test_hard_lock_round_trip_is_exact():
    """A HARD_LOCK 4.5 mm pin must read back 4.5 within its precision — it cannot silently drift."""
    locked = _pd(4.5, 3.0, 6.0, lock=LockState.HARD_LOCK)
    assert abs(locked.value - 4.5) <= locked.precision


def test_out_of_recommended_range_parameter_is_constructible_but_flagged():
    """Bounds are advisory — the copilot may propose values outside the recommended range when the
    user's intent warrants it. A ParameterDef with value outside [lo, hi] still constructs; it just
    reports `is_within_recommended() == False` and its mutation carries APPLIED_ADVISORY status."""
    pd_out = _pd(10.0, 1.0, 5.0)
    assert pd_out.value == 10.0
    assert not pd_out.is_within_recommended()


def test_inverted_bounds_still_rejected_as_sanity():
    """Only the lo<=hi sanity check remains — a subsystem author cannot ship inverted bounds."""
    with pytest.raises(ValueError):
        _pd(3.0, 5.0, 1.0)  # lo > hi


def test_llm_cannot_target_derived_or_review_nodes():
    assert is_forbidden_target("derived.factor_of_safety")
    assert is_forbidden_target("review.state")
    assert not is_forbidden_target("instances.root.params.skin_thickness_mm")
