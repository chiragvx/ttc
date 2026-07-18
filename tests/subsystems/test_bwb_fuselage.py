"""BWB fuselage — blended-wing-body: one continuous full-span loft, thick airfoil centerbody
smoothly tapering (chord + thickness_pct together) to thin wing-like tips. `naca_wing`'s sibling —
see bwb_fuselage.py's module docstring for why this one uses ease_at/ruled=False instead of that
file's plain-linear/ruled=True choice."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "bwb_fuselage" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("bwb_fuselage")
    assert sub.name == "bwb_fuselage"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "bwb_fuselage")
    v = get_subsystem("bwb_fuselage").volume_mm3(led)
    assert v > 0.0


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "bwb_fuselage")
    reasons = get_subsystem("bwb_fuselage").check_invariants(led)
    assert reasons == [], f"bwb_fuselage default seeds must satisfy invariants: {reasons}"


def test_blend_taper_overlap_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "bwb_fuselage", blend_taper_mm=(500.0, 0.0, 1500.0))
    reasons = get_subsystem("bwb_fuselage").check_invariants(led)
    assert any("overlap" in r for r in reasons)


def test_blend_taper_at_half_span_boundary_is_ok(base_ledger, seeded_with):
    # blend_taper_mm == span_mm / 2 exactly -- no flat centerbody left, but not an overlap either.
    led = seeded_with(base_ledger, "bwb_fuselage", blend_taper_mm=(400.0, 0.0, 1500.0))
    reasons = get_subsystem("bwb_fuselage").check_invariants(led)
    assert reasons == [], f"blend_taper_mm at exactly span_mm/2 must be valid: {reasons}"


def test_reversed_chord_taper_violates(base_ledger, seeded_with):
    # THE naca_wing.py regression, applied here: tip_chord_mm must never exceed centerbody_chord_mm --
    # a BWB blends FROM a thick body TO a thin tip, never the reverse, and no aggregate integral
    # (volume, area) can ever catch this on its own (see naca_wing.py's own module docstring / commit).
    led = seeded_with(base_ledger, "bwb_fuselage", tip_chord_mm=(400.0, 10.0, 1500.0))
    reasons = get_subsystem("bwb_fuselage").check_invariants(led)
    assert any("tip_chord_mm" in r and "centerbody_chord_mm" in r for r in reasons)


def test_reversed_thickness_taper_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "bwb_fuselage", tip_thickness_pct=(35.0, 6.0, 40.0))
    reasons = get_subsystem("bwb_fuselage").check_invariants(led)
    assert any("tip_thickness_pct" in r and "centerbody_thickness_pct" in r for r in reasons)


def test_tip_too_thin_violates_min_wall(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "bwb_fuselage",
                     tip_chord_mm=(10.0, 10.0, 600.0), tip_thickness_pct=(6.0, 6.0, 21.0))
    reasons = get_subsystem("bwb_fuselage").check_invariants(led)
    assert any("max thickness at the tip" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "bwb_fuselage")
    part = get_subsystem("bwb_fuselage").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1
    assert "bwb.body" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_with_no_flat_centerbody(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "bwb_fuselage", blend_taper_mm=(400.0, 0.0, 1500.0))
    part = get_subsystem("bwb_fuselage").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_with_sweep_and_dihedral(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "bwb_fuselage",
                     sweep_deg=(35.0, -30.0, 45.0), dihedral_deg=(8.0, -10.0, 20.0))
    part = get_subsystem("bwb_fuselage").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_centerbody_is_thicker_than_tip(base_ledger, seeded):
    # THE feature this subsystem exists for: the centerline cross-section must be visibly thicker
    # (in real Z extent) than the tip cross-section -- not just a param value, the actual built solid.
    led = seeded(base_ledger, "bwb_fuselage")
    part = get_subsystem("bwb_fuselage").geometry_builder(led)
    bb = part.solid.bounding_box()
    z_half_extent = (bb.max.Z - bb.min.Z) / 2.0
    from packages.subsystems import get_subsystem_model
    from packages.subsystems.base import Namespace
    from packages.ledger.parameter import ParameterDef
    sub = get_subsystem_model("bwb_fuselage")
    resolved = {spec.name: ParameterDef(value=spec.value, unit=spec.unit, bounds=(spec.min, spec.max))
                for spec in sub.params}
    ns = Namespace(resolved)
    tip_thickness_mm = ns.tip_chord_mm * ns.tip_thickness_pct / 100.0
    assert z_half_extent > tip_thickness_mm, (
        f"expected the built solid's max half-thickness ({z_half_extent:.1f} mm) to exceed the tip's "
        f"own thickness ({tip_thickness_mm:.1f} mm) -- the centerbody should visibly bulge"
    )


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "bwb_fuselage")
    approx = get_subsystem("bwb_fuselage").volume_mm3(led)
    part = get_subsystem("bwb_fuselage").geometry_builder(led)
    real = part.solid.volume
    rel_err = abs(approx - real) / real
    # Measured directly (module docstring): under ~1% across a 6-20 station-count sweep -- much
    # tighter than tube_fuselage's disclosed ~13-21%, since an airfoil section is thin relative to its
    # chord. Kept well above the measured figure, same honesty-not-looseness stance as every sibling.
    assert rel_err < 0.05, f"approx {approx:.1f} vs real build {real:.1f} volume (err {rel_err:.1%})"
