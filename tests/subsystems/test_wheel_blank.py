"""Wheel Blank — dedicated per-part correctness tests (bespoke, not just the catalog-wide
parametrized loop in test_subsystems.py / test_general_hardware_catalog.py).

Disc + hub, wide radial rim — a plain solid cylinder built via `bd.Cylinder(radius=dia_mm/2,
height=height_mm)`, sharing round_bar's/pulley_blank_flat's/round_post's cylinder shape family
and `cylinder_end_interfaces("height_mm")` for its two mount frames (see wheel_blank.py)."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems import wheel_blank as wheel_blank_module
from packages.subsystems.base import Namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(dia_mm: float, height_mm: float) -> Namespace:
    return Namespace({
        "dia_mm": ParameterDef(value=dia_mm, unit="mm", bounds=(15.0, 200.0)),
        "height_mm": ParameterDef(value=height_mm, unit="mm", bounds=(4.0, 50.0)),
    })


def test_registered():
    assert "wheel_blank" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("wheel_blank")
    assert sub.name == "wheel_blank"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


# --- volume -------------------------------------------------------------------

def test_volume_matches_hand_computed_cylinder():
    # dia_mm=80 -> radius=40; height_mm=20 -> V = pi * r^2 * h = pi * 1600 * 20 = pi * 32000
    p = _ns(dia_mm=80.0, height_mm=20.0)
    v = wheel_blank_module._volume(p)
    expected = math.pi * 32000.0
    assert v == pytest.approx(expected)
    assert v == pytest.approx(100530.9649, abs=1e-3)  # hand-computed literal, not just the formula echoed back


def test_volume_matches_hand_computed_at_ledger_defaults(base_ledger, seeded):
    # dia_mm=60.0 default -> radius=30; height_mm=15.0 default -> V = pi * 900 * 15 = pi * 13500
    led = seeded(base_ledger, "wheel_blank")
    v = get_subsystem("wheel_blank").volume_mm3(led)
    assert v == pytest.approx(math.pi * 13500.0)
    assert v == pytest.approx(42411.5008, abs=1e-3)


# --- interfaces / mate frames ---------------------------------------------------

def test_interfaces_declare_bottom_and_top_at_exact_coordinates():
    sub = get_subsystem_model("wheel_blank")
    assert [i.name for i in sub.interfaces] == ["bottom", "top"]
    p = _ns(dia_mm=80.0, height_mm=20.0)  # half-height = 10
    bottom = next(i for i in sub.interfaces if i.name == "bottom").frame(p)
    top = next(i for i in sub.interfaces if i.name == "top").frame(p)
    assert bottom.origin == pytest.approx((0.0, 0.0, -10.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 10.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


def test_end_interfaces_track_a_non_default_height():
    # The frame is a CALLABLE over resolved params, not a cached constant -- changing height_mm must
    # move both interfaces with it (dia_mm plays no part in either end's coordinates).
    ns = _ns(dia_mm=60.0, height_mm=15.0)  # catalog defaults, half-height = 7.5
    interfaces = {i.name: i for i in get_subsystem_model("wheel_blank").interfaces}
    assert interfaces["bottom"].frame(ns).origin == pytest.approx((0.0, 0.0, -7.5))
    assert interfaces["top"].frame(ns).origin == pytest.approx((0.0, 0.0, 7.5))


# --- invariants -----------------------------------------------------------------

def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "wheel_blank")
    reasons = get_subsystem("wheel_blank").check_invariants(led)
    assert reasons == [], f"wheel_blank default seeds must satisfy invariants: {reasons}"


def test_too_thin_height_violates_min_wall():
    # Deliberately invalid: height_mm=0.5 < the 0.8mm min-wall floor wheel_blank._check enforces.
    p = _ns(dia_mm=60.0, height_mm=0.5)
    reasons = wheel_blank_module._check(p)
    assert reasons == ["height 0.50 mm < min wall 0.8 mm"]
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_check_called_directly_is_clean_at_the_boundary_and_above():
    assert wheel_blank_module._check(_ns(dia_mm=60.0, height_mm=0.8)) == []  # exactly at the floor -- not "< 0.8"
    assert wheel_blank_module._check(_ns(dia_mm=60.0, height_mm=15.0)) == []  # catalog default


def test_too_thin_height_violates_min_wall_via_ledger(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "wheel_blank", height_mm=(0.5, 0.1, 50))
    reasons = get_subsystem("wheel_blank").check_invariants(led)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


# --- real geometry ----------------------------------------------------------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_and_tags(base_ledger, seeded):
    led = seeded(base_ledger, "wheel_blank")
    part = get_subsystem("wheel_blank").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "wheel_blank")
    approx = get_subsystem("wheel_blank").volume_mm3(led)
    real = get_subsystem("wheel_blank").geometry_builder(led).solid.volume
    assert abs(approx - real) / real < 0.01
