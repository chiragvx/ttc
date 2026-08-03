"""Mounting bracket — dedicated per-part correctness tests (bespoke, not just the catalog-wide
parametrized loop in test_subsystems.py / test_valid_ranges.py).

Flat plate + a row of bolt holes, built via `packages.truth_plane.regen.templated.render_bracket`
(see bracket.py). `_volume` is a plain box product (width * depth * skin_thickness); its two mount
frames come from the shared `plate_face_interfaces("skin_thickness_mm")` helper (+/- Z faces); its
own edge-distance invariant bounds hole_diameter_mm to <= plate_depth_mm / 3."""

from __future__ import annotations

import importlib.util

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems import bracket as bracket_module
from packages.subsystems.base import Namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(plate_width_mm: float, plate_depth_mm: float, skin_thickness_mm: float,
        hole_diameter_mm: float = 6.0, hole_count: float = 4.0,
        internal_rib_spacing_mm: float = 20.0) -> Namespace:
    return Namespace({
        "plate_width_mm":          ParameterDef(value=plate_width_mm, unit="mm", bounds=(40.0, 120.0)),
        "plate_depth_mm":          ParameterDef(value=plate_depth_mm, unit="mm", bounds=(30.0, 80.0)),
        "skin_thickness_mm":       ParameterDef(value=skin_thickness_mm, unit="mm", bounds=(1.0, 5.0)),
        "hole_diameter_mm":        ParameterDef(value=hole_diameter_mm, unit="mm", bounds=(3.0, 10.0)),
        "hole_count":              ParameterDef(value=hole_count, unit="count", bounds=(1.0, 12.0)),
        "internal_rib_spacing_mm": ParameterDef(value=internal_rib_spacing_mm, unit="mm", bounds=(10.0, 50.0)),
    })


def test_registered():
    assert "bracket" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("bracket")
    assert sub.name == "bracket"
    assert set(sub.applicable_disciplines) == {"structures", "manufacturing", "thermal"}


def test_volume_matches_hand_computed_box_product():
    # width=80, depth=50, thickness=3 -> V = 80 * 50 * 3 = 12000 mm^3 (plain box product, no holes
    # subtracted -- bracket._volume deliberately doesn't net out bolt-hole material, see bracket.py).
    p = _ns(plate_width_mm=80.0, plate_depth_mm=50.0, skin_thickness_mm=3.0)
    v = bracket_module._volume(p)
    assert v == pytest.approx(80.0 * 50.0 * 3.0)
    assert v == pytest.approx(12000.0)  # hand-computed literal, not just the formula echoed back


def test_volume_matches_hand_computed_at_ledger_defaults(base_ledger, seeded):
    # defaults: plate_width_mm=60, plate_depth_mm=40, skin_thickness_mm=2.0 -> V = 60*40*2 = 4800
    led = seeded(base_ledger, "bracket")
    v = get_subsystem("bracket").volume_mm3(led)
    assert v == pytest.approx(4800.0)


def test_interfaces_declare_top_and_bottom_at_exact_coordinates():
    sub = get_subsystem_model("bracket")
    assert [i.name for i in sub.interfaces] == ["top", "bottom"]
    p = _ns(plate_width_mm=80.0, plate_depth_mm=50.0, skin_thickness_mm=3.0)  # half-thickness = 1.5
    top = next(i for i in sub.interfaces if i.name == "top").frame(p)
    bottom = next(i for i in sub.interfaces if i.name == "bottom").frame(p)
    assert top.origin == pytest.approx((0.0, 0.0, 1.5))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))
    assert bottom.origin == pytest.approx((0.0, 0.0, -1.5))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "bracket")
    reasons = get_subsystem("bracket").check_invariants(led)
    assert reasons == [], f"bracket default seeds must satisfy invariants: {reasons}"


def test_oversized_hole_violates_edge_distance_rule():
    # Deliberately invalid: plate_depth_mm=30 -> max_dia = 30/3 = 10.0mm; hole_diameter_mm=11.0 > 10.0
    # trips bracket._check's edge-distance rule (hole_dia <= plate_depth/3).
    p = _ns(plate_width_mm=60.0, plate_depth_mm=30.0, skin_thickness_mm=2.0, hole_diameter_mm=11.0)
    reasons = bracket_module._check(p)
    assert reasons != []
    assert any("edge distance" in r for r in reasons)


def test_oversized_hole_violates_edge_distance_rule_via_ledger(base_ledger, seeded_with):
    # Same rule, exercised through the registered ledger-facing wrapper: widen hole_diameter_mm's own
    # bounds so the value itself isn't rejected before check_invariants ever runs, then confirm the
    # cross-field edge-distance rule (independent of hole_diameter_mm's own soft bounds) still fires.
    led = seeded_with(base_ledger, "bracket", hole_diameter_mm=(15.0, 1.0, 30.0))
    reasons = get_subsystem("bracket").check_invariants(led)
    assert any("edge distance" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_and_tags(base_ledger, seeded):
    led = seeded(base_ledger, "bracket")
    part = get_subsystem("bracket").geometry_builder(led)
    assert part.solid is not None
    assert "plate.body" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    # bracket._volume is a plain box product that ignores the bolt holes it also renders, so this is
    # a loose sanity check (holes remove real material) rather than a tight cross-check like cap_nut's.
    led = seeded(base_ledger, "bracket")
    approx = get_subsystem("bracket").volume_mm3(led)
    real = get_subsystem("bracket").geometry_builder(led).solid.volume
    assert real < approx  # holes strictly remove material from the plain box product
    assert abs(approx - real) / approx < 0.05
