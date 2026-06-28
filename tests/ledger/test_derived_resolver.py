"""Derived resolution: a verdict fills `derived` for its geometry and auto-invalidates on change."""

from __future__ import annotations

from packages.ledger.derived_resolver import (
    Verdict,
    geometry_signature,
    latest_verdict,
    ledger_with_derived,
    resolve_derived,
)
from packages.ledger.gates import ExportStatus, evaluate_export_gates
from packages.ledger.schema import Review, ReviewState

FP = "fp-abc"


def _verdict(sig: str, fs: float = 4.0) -> Verdict:
    return Verdict(geometry_signature=sig, fingerprint=FP, factor_of_safety=fs,
                   mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=3.2)


def test_matching_verdict_fills_derived(base_ledger):
    sig = geometry_signature(base_ledger)
    d = resolve_derived(base_ledger, [_verdict(sig)], fingerprint=FP)
    assert d.factor_of_safety == 4.0 and d.watertight is True


def test_no_verdict_is_unknown(base_ledger):
    assert resolve_derived(base_ledger, [], fingerprint=FP).factor_of_safety is None


def test_changing_geometry_invalidates_verdict(base_ledger, pd_factory):
    sig = geometry_signature(base_ledger)
    verdicts = [_verdict(sig)]
    assert latest_verdict(base_ledger, verdicts, fingerprint=FP) is not None
    # change a geometry param -> signature changes -> the old verdict no longer matches
    base_ledger.domains.structure.skin_thickness_mm = pd_factory(3.0, 1.0, 5.0)
    assert latest_verdict(base_ledger, verdicts, fingerprint=FP) is None
    assert resolve_derived(base_ledger, verdicts, fingerprint=FP).factor_of_safety is None


def test_resizing_a_bolt_hole_invalidates_verdict(base_ledger, pd_factory):
    # hole diameter is a tunable geometry param: changing it alters the FEA stress field, so a verdict
    # for the old hole size must NOT silently stand for the new one
    sig = geometry_signature(base_ledger)
    verdicts = [_verdict(sig)]
    assert latest_verdict(base_ledger, verdicts, fingerprint=FP) is not None
    base_ledger.domains.manufacturing.hole_diameter_mm = pd_factory(8.0, 3.0, 10.0)
    assert latest_verdict(base_ledger, verdicts, fingerprint=FP) is None


def test_resizing_the_plate_footprint_invalidates_verdict(base_ledger, pd_factory):
    # plate width/depth are tunable geometry: changing the footprint changes the FEA, so an old verdict
    # must not stand for the new size
    sig = geometry_signature(base_ledger)
    verdicts = [_verdict(sig)]
    assert latest_verdict(base_ledger, verdicts, fingerprint=FP) is not None
    base_ledger.domains.structure.plate_width_mm = pd_factory(90.0, 40.0, 120.0)
    assert latest_verdict(base_ledger, verdicts, fingerprint=FP) is None


def test_fingerprint_mismatch_invalidates(base_ledger):
    sig = geometry_signature(base_ledger)
    assert latest_verdict(base_ledger, [_verdict(sig)], fingerprint="different") is None


def test_export_gate_flips_with_verdict_and_signoff(base_ledger):
    sig = geometry_signature(base_ledger)
    verdicts = [_verdict(sig, fs=4.0)]
    base_ledger.review = Review(state=ReviewState.ENGINEER_REVIEWED, reviewer="pe@x")

    eligible = ledger_with_derived(base_ledger, verdicts, fingerprint=FP)
    assert evaluate_export_gates(eligible).status is ExportStatus.EXPORT_ELIGIBLE

    # with no matching verdict (e.g. params changed) it goes back to blocked
    blocked = ledger_with_derived(base_ledger, [], fingerprint=FP)
    assert evaluate_export_gates(blocked).status is ExportStatus.EXPORT_BLOCKED
