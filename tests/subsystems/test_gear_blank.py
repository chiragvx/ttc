"""Gear blank — dedicated per-part correctness tests (bespoke, not just the catalog-wide
parametrized loop in test_subsystems.py / test_general_hardware_catalog.py).

Gear disc with hub, no teeth (spec: dp, N) — a plain solid cylinder built via
`bd.Cylinder(radius=dia_mm/2, height=height_mm)`, sharing round_post's/longeron's/
pulley_blank_flat's cylinder shape family and `cylinder_end_interfaces("height_mm")` for its two
mount frames (see gear_blank.py)."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems import gear_blank as gear_blank_module
from packages.subsystems.base import Namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(dia_mm: float, height_mm: float) -> Namespace:
    return Namespace({
        "dia_mm": ParameterDef(value=dia_mm, unit="mm", bounds=(10.0, 120.0)),
        "height_mm": ParameterDef(value=height_mm, unit="mm", bounds=(3.0, 35.0)),
    })


def test_registered():
    assert "gear_blank" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("gear_blank")
    assert sub.name == "gear_blank"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_volume_matches_hand_computed_cylinder():
    # dia_mm=50 -> radius=25; height_mm=12 -> V = pi * r^2 * h = pi * 625 * 12 = pi * 7500
    p = _ns(dia_mm=50.0, height_mm=12.0)
    v = gear_blank_module._volume(p)
    expected = math.pi * 7500.0
    assert v == pytest.approx(expected)
    assert v == pytest.approx(23561.9449, abs=1e-3)  # hand-computed literal, not just the formula echoed back


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "gear_blank")
    v = get_subsystem("gear_blank").volume_mm3(led)
    assert v > 0.0


def test_volume_matches_hand_computed_at_ledger_defaults(base_ledger, seeded):
    # dia_mm=35.0 default -> radius=17.5; height_mm=10.0 default -> V = pi * 306.25 * 10 = pi * 3062.5
    led = seeded(base_ledger, "gear_blank")
    v = get_subsystem("gear_blank").volume_mm3(led)
    assert v == pytest.approx(math.pi * 3062.5)


def test_interfaces_declare_bottom_and_top_at_exact_coordinates():
    sub = get_subsystem_model("gear_blank")
    assert [i.name for i in sub.interfaces] == ["bottom", "top"]
    p = _ns(dia_mm=50.0, height_mm=12.0)  # half-height = 6.0
    bottom = next(i for i in sub.interfaces if i.name == "bottom").frame(p)
    top = next(i for i in sub.interfaces if i.name == "top").frame(p)
    assert bottom.origin == pytest.approx((0.0, 0.0, -6.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 6.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "gear_blank")
    reasons = get_subsystem("gear_blank").check_invariants(led)
    assert reasons == [], f"gear_blank default seeds must satisfy invariants: {reasons}"


def test_too_thin_height_violates_min_wall():
    # Deliberately invalid: height_mm=0.5 < the 0.8mm min-wall floor gear_blank._check enforces.
    p = _ns(dia_mm=40.0, height_mm=0.5)
    reasons = gear_blank_module._check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_too_thin_height_violates_min_wall_via_ledger(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "gear_blank", height_mm=(0.5, 0.1, 50))
    reasons = get_subsystem("gear_blank").check_invariants(led)
    assert any("min wall" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_and_tags(base_ledger, seeded):
    led = seeded(base_ledger, "gear_blank")
    part = get_subsystem("gear_blank").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "gear_blank")
    approx = get_subsystem("gear_blank").volume_mm3(led)
    real = get_subsystem("gear_blank").geometry_builder(led).solid.volume
    assert abs(approx - real) / real < 0.01
