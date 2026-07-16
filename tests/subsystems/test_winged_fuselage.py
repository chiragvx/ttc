"""Winged fuselage — lofted_spindle fuselage + naca_wing panel, boolean-fused into ONE continuous
printable solid. See winged_fuselage.py's module docstring for the placement/rotation reasoning this
file's tests are built to catch a regression in."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "winged_fuselage" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("winged_fuselage")
    assert sub.name == "winged_fuselage"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "winged_fuselage")
    v = get_subsystem("winged_fuselage").volume_mm3(led)
    assert v > 0.0


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "winged_fuselage")
    reasons = get_subsystem("winged_fuselage").check_invariants(led)
    assert reasons == [], f"winged_fuselage default seeds must satisfy invariants: {reasons}"


def test_invariants_catch_child_violations(base_ledger, seeded_with):
    # a violation in the (reused) lofted_spindle invariant set must still surface here.
    led = seeded_with(base_ledger, "winged_fuselage",
                     start_taper_mm=(300.0, 0.0, 1000.0), end_taper_mm=(300.0, 0.0, 1000.0))
    reasons = get_subsystem("winged_fuselage").check_invariants(led)
    assert any("exceeds" in r and "length" in r for r in reasons)
    # and a violation in the (reused) naca_wing invariant set too.
    led2 = seeded_with(base_ledger, "winged_fuselage",
                      tip_chord_mm=(10.0, 10.0, 600.0), thickness_pct=(6.0, 6.0, 21.0))
    reasons2 = get_subsystem("winged_fuselage").check_invariants(led2)
    assert any("max thickness" in r for r in reasons2)
    # ...including naca_wing's reversed-taper check (this composite's own _check() delegates to
    # NACA_WING.invariants(p) verbatim -- the fix propagates here for free, confirmed rather than assumed).
    led3 = seeded_with(base_ledger, "winged_fuselage",
                      root_chord_mm=(20.0, 20.0, 600.0), tip_chord_mm=(600.0, 10.0, 600.0))
    reasons3 = get_subsystem("winged_fuselage").check_invariants(led3)
    assert any("taper root-to-tip" in r for r in reasons3)


def test_invariants_catch_wing_span_too_short_to_cross_fuselage_shell(base_ledger, seeded_with):
    """A real, reproducible bug this file's tests originally missed: span_mm at its own declared
    100mm floor combined with max_width_mm only slightly above its own 80mm default (both fully
    inside their declared ParamSpec bounds, default wing_position_pct=50) leaves the wing's half-span
    (50mm) BELOW the fuselage's own half-width at the waist (52.5mm) -- the wing sits entirely
    embedded inside the fuselage's SOLID body (ogive_fuselage went solid 2026-07-06) and never
    reaches its own outer surface. check_invariants() must catch this instead of silently reporting
    no violations."""
    led = seeded_with(base_ledger, "winged_fuselage",
                      span_mm=(100.0, 100.0, 3000.0), max_width_mm=(105.0, 20.0, 500.0))
    reasons = get_subsystem("winged_fuselage").check_invariants(led)
    assert any("half-span" in r and "half-width" in r for r in reasons), (
        f"expected a wing-span-vs-fuselage-width crossing violation, got: {reasons}"
    )

    if not HAS_B123D:
        pytest.skip("needs build123d for the geometry-level confirmation")

    # Confirm this is a REAL geometric problem, not just an overly-strict invariant: against a SOLID
    # fuselage, an engulfed wing fuses into ONE solid (not two disjoint bodies) whose volume equals
    # the fuselage alone -- the wing contributes zero extra volume because it never reaches the
    # fuselage's outer surface.
    part = get_subsystem("winged_fuselage").geometry_builder(led)
    assert part.solid.is_valid is True
    assert len(part.solid.solids()) == 1

    from packages.subsystems import call
    fuselage_only = call(
        "ogive_fuselage",
        length_mm=led.instances[led.root_id].params["length_mm"].value,
        max_width_mm=led.instances[led.root_id].params["max_width_mm"].value,
        max_height_mm=led.instances[led.root_id].params["max_height_mm"].value,
        start_taper_mm=led.instances[led.root_id].params["start_taper_mm"].value,
        end_taper_mm=led.instances[led.root_id].params["end_taper_mm"].value,
        start_width_mm=led.instances[led.root_id].params["start_width_mm"].value,
        start_height_mm=led.instances[led.root_id].params["start_height_mm"].value,
        end_width_mm=led.instances[led.root_id].params["end_width_mm"].value,
        end_height_mm=led.instances[led.root_id].params["end_height_mm"].value,
        taper_power=led.instances[led.root_id].params["taper_power"].value,
    )
    assert part.solid.volume == pytest.approx(fuselage_only.solid.volume, rel=1e-6), (
        "expected this under-margin config to reproduce the known wing-fully-engulfed bug -- the "
        "fused volume should equal the fuselage alone"
    )


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "winged_fuselage")
    part = get_subsystem("winged_fuselage").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_fuse_produces_one_real_manifold_not_two_touching_solids(base_ledger, seeded):
    """THE single most important correctness signal for this whole subsystem: after fuse(), the
    result must be ONE valid manifold solid (a real boolean union happened, at a genuine 3D overlap
    -- see winged_fuselage.py's module docstring on why the wing root/fuselage placement guarantees
    that), not two solids that merely happen to touch or sit inside a Compound."""
    led = seeded(base_ledger, "winged_fuselage")
    part = get_subsystem("winged_fuselage").geometry_builder(led)
    assert part.solid.is_valid is True
    assert len(part.solid.solids()) == 1

    # And a sanity check on the union itself: the fused body's volume must be LESS than the naive sum
    # of the two children's own real volumes (since a real union subtracts the overlap region), but
    # still comfortably more than either child alone (the wing didn't vanish/get engulfed, the
    # fuselage didn't vanish either).
    from packages.subsystems import call
    fuselage_only = call(
        "ogive_fuselage",
        length_mm=led.instances[led.root_id].params["length_mm"].value,
        max_width_mm=led.instances[led.root_id].params["max_width_mm"].value,
        max_height_mm=led.instances[led.root_id].params["max_height_mm"].value,
        start_taper_mm=led.instances[led.root_id].params["start_taper_mm"].value,
        end_taper_mm=led.instances[led.root_id].params["end_taper_mm"].value,
        start_width_mm=led.instances[led.root_id].params["start_width_mm"].value,
        start_height_mm=led.instances[led.root_id].params["start_height_mm"].value,
        end_width_mm=led.instances[led.root_id].params["end_width_mm"].value,
        end_height_mm=led.instances[led.root_id].params["end_height_mm"].value,
        taper_power=led.instances[led.root_id].params["taper_power"].value,
    )
    wing_only = call(
        "naca_wing",
        span_mm=led.instances[led.root_id].params["span_mm"].value,
        root_chord_mm=led.instances[led.root_id].params["root_chord_mm"].value,
        tip_chord_mm=led.instances[led.root_id].params["tip_chord_mm"].value,
        thickness_pct=led.instances[led.root_id].params["thickness_pct"].value,
        sweep_deg=led.instances[led.root_id].params["sweep_deg"].value,
        dihedral_deg=led.instances[led.root_id].params["dihedral_deg"].value,
    )
    naive_sum = fuselage_only.solid.volume + wing_only.solid.volume
    assert part.solid.volume < naive_sum
    assert part.solid.volume > fuselage_only.solid.volume
    assert part.solid.volume > wing_only.solid.volume


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_at_wing_position_extremes(base_ledger, seeded_with):
    """The wing must still fuse into one real manifold body near either end of the fuselage's
    start/end taper zones, not just at the default mid-body waist."""
    for pct in (20.0, 80.0):
        led = seeded_with(base_ledger, "winged_fuselage", wing_position_pct=(pct, 0.0, 100.0))
        part = get_subsystem("winged_fuselage").geometry_builder(led)
        assert part.solid.is_valid
        assert len(part.solid.solids()) == 1, f"expected one fused solid at wing_position_pct={pct}"


def test_section_tags_present_with_no_geometric_side_effect(base_ledger, seeded_with):
    """section_a_pct/section_b_pct are pure inert metadata -- present in tags, but changing them must
    not move a single atom of the actual solid (checked here via the closed-form volume estimator,
    which is exactly what the fast interactive plane relies on)."""
    sub = get_subsystem("winged_fuselage")
    led1 = seeded_with(base_ledger, "winged_fuselage",
                       section_a_pct=(30.0, 0.0, 100.0), section_b_pct=(70.0, 0.0, 100.0))
    led2 = seeded_with(base_ledger, "winged_fuselage",
                       section_a_pct=(10.0, 0.0, 100.0), section_b_pct=(95.0, 0.0, 100.0))

    v1 = sub.volume_mm3(led1)
    v2 = sub.volume_mm3(led2)
    assert v1 == v2, "section_a_pct/section_b_pct must have NO effect on geometry/volume"

    if not HAS_B123D:
        pytest.skip("needs build123d for the tag/solid-volume check")

    part1 = sub.geometry_builder(led1)
    part2 = sub.geometry_builder(led2)
    assert "fuselage.section_a" in part1.tag_keys
    assert "fuselage.section_b" in part1.tag_keys
    assert part1.tags["fuselage.section_a"]["z_mm"] == pytest.approx(
        led1.instances[led1.root_id].params["length_mm"].value * 0.30
    )
    assert part1.tags["fuselage.section_b"]["z_mm"] == pytest.approx(
        led1.instances[led1.root_id].params["length_mm"].value * 0.70
    )
    assert part2.tags["fuselage.section_a"]["z_mm"] == pytest.approx(
        led2.instances[led2.root_id].params["length_mm"].value * 0.10
    )
    assert part1.solid.volume == pytest.approx(part2.solid.volume, rel=1e-9)
