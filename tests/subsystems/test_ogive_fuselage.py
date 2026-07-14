"""Ogive fuselage — streamlined body-of-revolution for aircraft/rocket fuselages, nose cones,
nacelles. lofted_spindle's aerospace-shaped sibling — power-law taper instead of cosine-ease."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "ogive_fuselage" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("ogive_fuselage")
    assert sub.name == "ogive_fuselage"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "ogive_fuselage")
    v = get_subsystem("ogive_fuselage").volume_mm3(led)
    assert v > 0.0


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "ogive_fuselage")
    reasons = get_subsystem("ogive_fuselage").check_invariants(led)
    assert reasons == [], f"ogive_fuselage default seeds must satisfy invariants: {reasons}"


def test_defaults_are_circular(base_ledger, seeded):
    led = seeded(base_ledger, "ogive_fuselage")
    inst = led.instances[led.root_id]
    assert inst.params["max_width_mm"].value == inst.params["max_height_mm"].value


def test_tapers_overlap_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "ogive_fuselage",
                     start_taper_mm=(300.0, 0.0, 1500.0), end_taper_mm=(300.0, 0.0, 1500.0))
    reasons = get_subsystem("ogive_fuselage").check_invariants(led)
    assert any("tapers overlap" in r for r in reasons)


def test_tip_width_not_narrower_than_max_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "ogive_fuselage", start_width_mm=(90.0, 0.0, 400.0))
    reasons = get_subsystem("ogive_fuselage").check_invariants(led)
    assert any("start_width" in r and "max_width" in r for r in reasons)


def test_taper_power_bounds_stay_valid(base_ledger, seeded_with):
    # Both declared extremes (steep near-tip ogive at 0.3, concave pin-like taper at 2.0) must stay
    # invariant-clean — taper_power reshapes the curve, it never becomes an invalid configuration on
    # its own within its declared ParamSpec bounds.
    for power in (0.3, 2.0):
        led = seeded_with(base_ledger, "ogive_fuselage", taper_power=(power, 0.3, 2.0))
        reasons = get_subsystem("ogive_fuselage").check_invariants(led)
        assert reasons == [], f"taper_power={power} must satisfy invariants: {reasons}"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "ogive_fuselage")
    part = get_subsystem("ogive_fuselage").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1
    assert "fuselage.body" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_fully_pointed_both_ends(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "ogive_fuselage",
                     start_width_mm=(0.0, 0.0, 400.0), start_height_mm=(0.0, 0.0, 400.0),
                     end_width_mm=(0.0, 0.0, 400.0), end_height_mm=(0.0, 0.0, 400.0))
    part = get_subsystem("ogive_fuselage").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_flattened_ellipse(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "ogive_fuselage",
                     max_width_mm=(80.0, 10.0, 400.0), max_height_mm=(30.0, 10.0, 400.0),
                     start_width_mm=(8.0, 0.0, 400.0), start_height_mm=(4.0, 0.0, 400.0),
                     end_width_mm=(4.0, 0.0, 400.0), end_height_mm=(2.0, 0.0, 400.0))
    part = get_subsystem("ogive_fuselage").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    bb = part.solid.bounding_box()
    y_size = bb.max.Y - bb.min.Y
    z_size = bb.max.Z - bb.min.Z
    assert abs(y_size - z_size) / max(y_size, z_size) > 0.2, (
        f"expected a noticeably non-square cross-section, got Y={y_size:.1f} Z={z_size:.1f}"
    )


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_nose_flares_immediately_not_a_flat_neck(base_ledger, seeded):
    # THE regression this subsystem exists to fix: lofted_spindle's cosine-ease taper stays nearly
    # flat right at the tip before flaring out (a "neck", per the user's own "squished bottle"
    # complaint on winged_fuselage). At a small fraction into the nose taper zone, the ogive's
    # power-law curve (power < 1) must have already grown noticeably past the tip radius — not
    # lingered near it the way ease_at's zero-slope-at-the-boundary curve does.
    from packages.subsystems import get_subsystem_model
    from packages.subsystems.base import Namespace
    from packages.ledger.parameter import ParameterDef
    sub = get_subsystem_model("ogive_fuselage")
    resolved = {spec.name: ParameterDef(value=spec.value, unit=spec.unit, bounds=(spec.min, spec.max))
                for spec in sub.params}
    from packages.subsystems.ogive_fuselage import _width_at
    ns = Namespace(resolved)
    tip_half = ns.start_width_mm / 2.0
    max_half = ns.max_width_mm / 2.0
    # 10% of the way through the nose taper zone
    x_10pct = ns.start_taper_mm * 0.10
    half_at_10pct = _width_at(x_10pct, ns)
    frac_grown = (half_at_10pct - tip_half) / (max_half - tip_half)
    assert frac_grown > 0.15, (
        f"expected the ogive taper to have grown noticeably by 10% into the nose zone, got only "
        f"{frac_grown:.1%} of the way from tip to max radius — looks like a flat neck, not an ogive"
    )


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "ogive_fuselage")
    approx = get_subsystem("ogive_fuselage").volume_mm3(led)
    part = get_subsystem("ogive_fuselage").geometry_builder(led)
    real = part.solid.volume
    rel_err = abs(approx - real) / real
    assert rel_err < 0.15, f"approx {approx:.1f} vs real build {real:.1f} volume (err {rel_err:.1%})"
