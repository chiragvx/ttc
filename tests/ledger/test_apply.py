"""Rules-validator (apply_delta) behaviour."""

from __future__ import annotations

from packages.ledger.apply import ApplyStatus, apply_delta, resolve_path
from packages.ledger.deltas import ParameterDelta
from packages.ledger.parameter import LockState

SKIN = "instances.root.params.skin_thickness_mm"
HOLE = "instances.root.params.hole_diameter_mm"
RIB_SPACING = "instances.root.params.internal_rib_spacing_mm"


def test_in_bounds_change_is_applied(base_ledger):
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=SKIN, requested_value=3.0))
    assert out.status is ApplyStatus.APPLIED
    assert new.instances["root"].params["skin_thickness_mm"].value == 3.0
    assert base_ledger.instances["root"].params["skin_thickness_mm"].value == 2.0  # original untouched


def test_out_of_recommended_range_is_applied_advisory(base_ledger):
    """Bounds are advisory — a value outside the recommended range is still applied, with an
    APPLIED_ADVISORY status flagging that the copilot judged the request reasonable in context."""
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=SKIN, requested_value=9.0))
    assert out.status is ApplyStatus.APPLIED_ADVISORY
    assert new.instances["root"].params["skin_thickness_mm"].value == 9.0  # NOT clamped
    assert "outside recommended range" in out.message


def test_hard_lock_is_rejected(ledger_factory, pd_factory):
    led = ledger_factory()
    led.instances["root"].params["skin_thickness_mm"] = pd_factory(4.5, 1.0, 5.0, LockState.HARD_LOCK)
    new, out = apply_delta(led, ParameterDelta(target_node=SKIN, requested_value=3.0))
    assert out.status is ApplyStatus.REJECTED
    assert new.instances["root"].params["skin_thickness_mm"].value == 4.5


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
    assert new.instances["root"].params["skin_thickness_mm"].value == 2.0  # unchanged


# --- material_profile: the one string-valued target_node (2026-07-19 fix) ----------------------
MATERIAL = "domains.structure.material_profile"


def test_material_change_is_applied(base_ledger):
    assert base_ledger.domains.structure.material_profile == "PLA"
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=MATERIAL, requested_value="ABS"))
    assert out.status is ApplyStatus.APPLIED
    assert out.old_value == "PLA" and out.new_value == "ABS"
    assert new.domains.structure.material_profile == "ABS"
    assert base_ledger.domains.structure.material_profile == "PLA"  # original untouched


def test_unknown_material_name_is_rejected(base_ledger):
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=MATERIAL, requested_value="UNOBTANIUM"))
    assert out.status is ApplyStatus.REJECTED
    assert "unknown material" in out.message
    assert new.domains.structure.material_profile == "PLA"  # never touched


def test_numeric_value_sent_to_material_is_rejected(base_ledger):
    """A real type mismatch (the LLM should send the material NAME as a string) — a clean REJECTED,
    never a crash trying to compare a float against the material's own bounds (it has none)."""
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=MATERIAL, requested_value=6061.0))
    assert out.status is ApplyStatus.REJECTED
    assert "must be a string" in out.message
    assert new.domains.structure.material_profile == "PLA"


def test_string_value_sent_to_a_numeric_node_is_rejected(base_ledger):
    """The mirror-image mistake: a string sent to a normal ParameterDef-backed node must also cleanly
    REJECT, never crash comparing a str against (lo, hi) bounds."""
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=SKIN, requested_value="thick"))
    assert out.status is ApplyStatus.REJECTED
    assert "must be a number" in out.message
    assert new.instances["root"].params["skin_thickness_mm"].value == 2.0


def test_set_lock_on_material_is_rejected(base_ledger):
    new, out = apply_delta(
        base_ledger, ParameterDelta(target_node=MATERIAL, requested_value="ABS", set_lock=LockState.HARD_LOCK))
    assert out.status is ApplyStatus.REJECTED
    assert "cannot set_lock" in out.message
    assert new.domains.structure.material_profile == "PLA"


def test_material_change_never_invokes_cascade_rules(base_ledger):
    """A material swap has no geometric cascade effect — cascade_rules must never even be CALLED (it
    assumes a float requested_value; calling it here would break a subsystem's own arithmetic)."""
    calls = []
    def _spy_cascade(ledger, target, requested):
        calls.append((target, requested))
        return []
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=MATERIAL, requested_value="PETG"),
                           cascade_rules=_spy_cascade)
    assert out.status is ApplyStatus.APPLIED
    assert calls == []


# --- cascades: optional caller-supplied companion changes -------------------------------------


def test_cascade_applies_companion_change_to_sibling_param(base_ledger):
    def rule(ledger, target, requested):
        return [(RIB_SPACING, 25.0, "hole bump requires wider rib spacing")]

    new, out = apply_delta(base_ledger, ParameterDelta(target_node=HOLE, requested_value=7.0),
                            cascade_rules=rule)
    assert out.status is ApplyStatus.APPLIED
    assert new.instances["root"].params["hole_diameter_mm"].value == 7.0  # direct edit landed
    assert new.instances["root"].params["internal_rib_spacing_mm"].value == 25.0  # cascade landed
    assert len(out.cascades) == 1
    effect = out.cascades[0]
    assert effect.target == RIB_SPACING
    assert effect.old_value == 20.0
    assert effect.new_value == 25.0
    assert effect.reason == "hole bump requires wider rib spacing"


def test_cascade_targeting_hard_lock_is_silently_skipped(ledger_factory, pd_factory):
    led = ledger_factory()
    led.instances["root"].params["internal_rib_spacing_mm"] = pd_factory(20.0, 10.0, 50.0, LockState.HARD_LOCK)

    def rule(ledger, target, requested):
        return [(RIB_SPACING, 25.0, "would bump rib spacing but it is frozen")]

    new, out = apply_delta(led, ParameterDelta(target_node=HOLE, requested_value=7.0), cascade_rules=rule)
    assert out.status is ApplyStatus.APPLIED
    assert new.instances["root"].params["hole_diameter_mm"].value == 7.0  # direct edit still succeeds
    assert new.instances["root"].params["internal_rib_spacing_mm"].value == 20.0  # untouched, still locked
    assert out.cascades == []


def test_cascade_insufficient_to_satisfy_invariant_conflicts_atomically(base_ledger):
    def domain_checks(ledger):
        rib = ledger.instances["root"].params["internal_rib_spacing_mm"]
        return [] if rib.value >= 30.0 else [f"rib spacing {rib.value} below required minimum 30"]

    def rule(ledger, target, requested):
        return [(RIB_SPACING, 25.0, "bump rib spacing, but not enough to satisfy the invariant")]

    new, out = apply_delta(base_ledger, ParameterDelta(target_node=HOLE, requested_value=7.0),
                            domain_checks=domain_checks, cascade_rules=rule)
    assert out.status is ApplyStatus.CONFLICT
    assert new.instances["root"].params["hole_diameter_mm"].value == 6.0  # direct edit reverted
    assert new.instances["root"].params["internal_rib_spacing_mm"].value == 20.0  # cascade reverted too
    assert new is base_ledger  # atomic no-op: the ORIGINAL ledger object comes back unchanged


def test_resolve_path_returns_parameter_def_or_none(base_ledger):
    pd = resolve_path(base_ledger, HOLE)
    assert pd is not None
    assert pd.value == 6.0

    assert resolve_path(base_ledger, "instances.root.params.nope_mm") is None


def test_omitting_cascade_rules_matches_explicit_none(base_ledger):
    delta = ParameterDelta(target_node=SKIN, requested_value=3.0)
    new_omitted, out_omitted = apply_delta(base_ledger, delta)
    new_explicit, out_explicit = apply_delta(base_ledger, delta, cascade_rules=None)

    assert out_omitted.status is ApplyStatus.APPLIED
    assert out_explicit.status is ApplyStatus.APPLIED
    assert out_omitted.cascades == []
    assert out_explicit.cascades == []
    assert new_omitted.instances["root"].params["skin_thickness_mm"].value == 3.0
    assert new_explicit.instances["root"].params["skin_thickness_mm"].value == 3.0
