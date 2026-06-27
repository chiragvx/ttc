"""Rules-validator (apply_delta) behaviour."""

from __future__ import annotations

from packages.ledger.apply import ApplyStatus, apply_delta
from packages.ledger.deltas import ParameterDelta
from packages.ledger.parameter import LockState

SKIN = "domains.structure.skin_thickness_mm"


def test_in_bounds_change_is_applied(base_ledger):
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=SKIN, requested_value=3.0))
    assert out.status is ApplyStatus.APPLIED
    assert new.domains.structure.skin_thickness_mm.value == 3.0
    assert base_ledger.domains.structure.skin_thickness_mm.value == 2.0  # original untouched


def test_out_of_bounds_is_clamped(base_ledger):
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=SKIN, requested_value=9.0))
    assert out.status is ApplyStatus.CLAMPED
    assert new.domains.structure.skin_thickness_mm.value == 5.0  # clamped to upper bound


def test_hard_lock_is_rejected(ledger_factory, pd_factory):
    led = ledger_factory()
    led.domains.structure.skin_thickness_mm = pd_factory(4.5, 1.0, 5.0, LockState.HARD_LOCK)
    new, out = apply_delta(led, ParameterDelta(target_node=SKIN, requested_value=3.0))
    assert out.status is ApplyStatus.REJECTED
    assert new.domains.structure.skin_thickness_mm.value == 4.5


def test_forbidden_target_is_rejected(base_ledger):
    _, out = apply_delta(base_ledger, ParameterDelta(target_node="derived.factor_of_safety", requested_value=2.0))
    assert out.status is ApplyStatus.REJECTED


def test_unknown_node_is_rejected(base_ledger):
    _, out = apply_delta(base_ledger, ParameterDelta(target_node="domains.structure.nope_mm", requested_value=1.0))
    assert out.status is ApplyStatus.REJECTED


def test_coupled_invariant_violation_is_conflict(ledger_factory):
    # bounds allow below the MIN_WALL invariant -> in-bounds but invariant-breaking -> CONFLICT
    led = ledger_factory(skin_bounds=(0.5, 5.0))
    new, out = apply_delta(led, ParameterDelta(target_node=SKIN, requested_value=0.6))
    assert out.status is ApplyStatus.CONFLICT
    assert new.domains.structure.skin_thickness_mm.value == 2.0  # unchanged
