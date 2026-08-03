"""Cover plate — dedicated per-part correctness tests (bespoke, not just the catalog-wide
parametrized loop in test_subsystems.py / test_general_hardware_catalog.py).

Flat rectangular plate with a single central through-bore, built via
`bd.Box(width_mm, height_mm, thickness_mm) - bd.Cylinder(radius=bore_dia_mm/2, height=thickness_mm*2)`,
centered at the origin (see cover_plate.py), with `plate_face_interfaces("thickness_mm")` giving it
two mount frames ("top"/"bottom") at its +/- Z faces."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems import cover_plate as cover_plate_module
from packages.subsystems.base import Namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(width_mm: float, height_mm: float, thickness_mm: float, bore_dia_mm: float) -> Namespace:
    return Namespace({
        "width_mm": ParameterDef(value=width_mm, unit="mm", bounds=(20.0, 250.0)),
        "height_mm": ParameterDef(value=height_mm, unit="mm", bounds=(20.0, 250.0)),
        "thickness_mm": ParameterDef(value=thickness_mm, unit="mm", bounds=(0.8, 10.0)),
        "bore_dia_mm": ParameterDef(value=bore_dia_mm, unit="mm", bounds=(2.0, 100.0)),
    })


def test_registered():
    assert "cover_plate" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("cover_plate")
    assert sub.name == "cover_plate"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


# --- volume -------------------------------------------------------------------

def test_volume_matches_hand_computed_value():
    # width=100, height=50, thickness=6 -> box volume = 100*50*6 = 30000
    # bore_dia=20 -> radius=10 -> bore volume = pi * 10^2 * 6 = 600*pi
    p = _ns(width_mm=100.0, height_mm=50.0, thickness_mm=6.0, bore_dia_mm=20.0)
    v = cover_plate_module._volume(p)
    expected = 100.0 * 50.0 * 6.0 - math.pi * 10.0 ** 2 * 6.0
    assert v == pytest.approx(expected)
    assert v == pytest.approx(28115.0444, abs=1e-3)  # hand-computed literal, not just the formula echoed back


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "cover_plate")
    v = get_subsystem("cover_plate").volume_mm3(led)
    assert v > 0.0


def test_volume_matches_hand_computed_at_ledger_defaults(base_ledger, seeded):
    # defaults: width=60, height=40, thickness=3.0, bore_dia=15.0
    led = seeded(base_ledger, "cover_plate")
    v = get_subsystem("cover_plate").volume_mm3(led)
    expected = 60.0 * 40.0 * 3.0 - math.pi * 7.5 ** 2 * 3.0
    assert v == pytest.approx(expected)


# --- interfaces / mate frames ---------------------------------------------------

def test_interfaces_declare_top_and_bottom_at_exact_coordinates():
    sub = get_subsystem_model("cover_plate")
    assert [i.name for i in sub.interfaces] == ["top", "bottom"]
    p = _ns(width_mm=100.0, height_mm=50.0, thickness_mm=6.0, bore_dia_mm=20.0)  # half-thickness = 3.0
    top = next(i for i in sub.interfaces if i.name == "top").frame(p)
    bottom = next(i for i in sub.interfaces if i.name == "bottom").frame(p)
    assert top.origin == pytest.approx((0.0, 0.0, 3.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))
    assert bottom.origin == pytest.approx((0.0, 0.0, -3.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))


# --- invariants -----------------------------------------------------------------

def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "cover_plate")
    reasons = get_subsystem("cover_plate").check_invariants(led)
    assert reasons == [], f"cover_plate default seeds must satisfy invariants: {reasons}"


def test_bore_too_big_leaves_no_frame():
    # Deliberately invalid: a 20x20 plate with an 19mm bore leaves min(20,20) - 2*0.8 = 18.4mm of
    # frame available, and 19 >= 18.4 -> trips cover_plate._check's "leaves no frame" rule.
    p = _ns(width_mm=20.0, height_mm=20.0, thickness_mm=3.0, bore_dia_mm=19.0)
    reasons = cover_plate_module._check(p)
    assert reasons != []
    assert any("leaves no frame" in r for r in reasons)


def test_bore_too_big_leaves_no_frame_via_ledger(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "cover_plate",
                       width_mm=(20.0, 20.0, 250.0), height_mm=(20.0, 20.0, 250.0),
                       bore_dia_mm=(19.0, 2.0, 100.0))
    reasons = get_subsystem("cover_plate").check_invariants(led)
    assert any("leaves no frame" in r for r in reasons)


def test_too_thin_violates_min_wall():
    # Deliberately invalid: thickness_mm=0.5 < the 0.8mm min-wall floor cover_plate._check enforces.
    p = _ns(width_mm=100.0, height_mm=50.0, thickness_mm=0.5, bore_dia_mm=20.0)
    reasons = cover_plate_module._check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_and_tags(base_ledger, seeded):
    led = seeded(base_ledger, "cover_plate")
    part = get_subsystem("cover_plate").geometry_builder(led)
    assert part.solid is not None
    assert {"plate.body", "bore.thru"} <= part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "cover_plate")
    approx = get_subsystem("cover_plate").volume_mm3(led)
    real = get_subsystem("cover_plate").geometry_builder(led).solid.volume
    assert abs(approx - real) / real < 0.01
