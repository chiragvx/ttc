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


def test_chord_and_thickness_schedule_peaks_at_centerline(base_ledger, seeded):
    # THE regression this subsystem was fixed for this session: a real live build produced a
    # "bowtie" -- thick at both outer span edges, pinched thin at the true centerline, exactly
    # backwards from the intended thick-centerbody/thin-tip shape. Caught only by evaluating the
    # chord/thickness schedule AT SPECIFIC SPAN POSITIONS and checking which value lands where --
    # neither total volume nor the overall bounding box (both symmetric/position-agnostic) can ever
    # tell "thick in the middle" apart from "thick at the edges" (same class of blind spot
    # naca_wing.py's own reversed-taper fix found this session).
    from packages.subsystems import get_subsystem_model
    from packages.subsystems.base import Namespace
    from packages.ledger.parameter import ParameterDef
    from packages.subsystems.bwb_fuselage import _chord_at, _thickness_pct_at
    sub = get_subsystem_model("bwb_fuselage")
    resolved = {spec.name: ParameterDef(value=spec.value, unit=spec.unit, bounds=(spec.min, spec.max))
                for spec in sub.params}
    ns = Namespace(resolved)
    half_span = ns.span_mm / 2.0
    chord_at_center = _chord_at(0.0, ns)
    chord_at_tip = _chord_at(half_span, ns)
    thickness_at_center = _thickness_pct_at(0.0, ns)
    thickness_at_tip = _thickness_pct_at(half_span, ns)
    assert chord_at_center == pytest.approx(ns.centerbody_chord_mm, abs=0.5), (
        f"expected the CENTERLINE (dist=0) to carry centerbody_chord_mm ({ns.centerbody_chord_mm}), "
        f"got {chord_at_center:.1f} -- looks like the tip value landed at the center instead"
    )
    assert chord_at_tip == pytest.approx(ns.tip_chord_mm, abs=0.5), (
        f"expected the TIP (dist=span_mm/2) to carry tip_chord_mm ({ns.tip_chord_mm}), got "
        f"{chord_at_tip:.1f} -- looks like the centerbody value landed at the tip instead"
    )
    assert thickness_at_center == pytest.approx(ns.centerbody_thickness_pct, abs=0.5)
    assert thickness_at_tip == pytest.approx(ns.tip_thickness_pct, abs=0.5)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_real_build_is_widest_at_center_not_at_the_edges(base_ledger, seeded_with):
    # Same regression as the pure-schedule check above, but against the REAL built solid: slice the
    # solid's own geometry near the centerline vs near an outer edge and confirm the centerline
    # cross-section is genuinely the bigger one -- catches a bug in the schedule-to-loft wiring even
    # if _chord_at/_thickness_pct_at themselves were somehow correct.
    import build123d as bd
    led = seeded_with(base_ledger, "bwb_fuselage",
                     span_mm=(800.0, 200.0, 3000.0), centerbody_chord_mm=(300.0, 50.0, 1500.0),
                     tip_chord_mm=(80.0, 10.0, 600.0), blend_taper_mm=(300.0, 0.0, 1500.0),
                     sweep_deg=(0.0, -30.0, 45.0), dihedral_deg=(0.0, -10.0, 20.0))
    part = get_subsystem("bwb_fuselage").geometry_builder(led)
    solid = part.solid
    plane_center = bd.Plane(origin=(0, 0, 0), z_dir=(1, 0, 0))
    plane_near_tip = bd.Plane(origin=(390, 0, 0), z_dir=(1, 0, 0))
    section_center = solid.intersect(plane_center)
    section_near_tip = solid.intersect(plane_near_tip)
    area_center = section_center.area if section_center is not None else 0.0
    area_near_tip = section_near_tip.area if section_near_tip is not None else 0.0
    assert area_center > area_near_tip, (
        f"expected the centerline cross-section ({area_center:.1f} mm^2) to be bigger than the "
        f"near-tip cross-section ({area_near_tip:.1f} mm^2) -- got the reverse, the bowtie regression"
    )


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
