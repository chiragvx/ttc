"""Pulley blank flat — dedicated per-part correctness tests (bespoke, not just the catalog-wide
parametrized loop in test_subsystems.py).

Flat-face pulley — a plain solid cylinder built via `bd.Cylinder(radius=dia_mm/2, height=height_mm)`,
sharing round_post's/longeron's/cap_nut's cylinder shape family and `cylinder_end_interfaces("height_mm")`
for its two mount frames (see pulley_blank_flat.py)."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems import pulley_blank_flat as pulley_blank_flat_module
from packages.subsystems.base import Namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(dia_mm: float, height_mm: float) -> Namespace:
    return Namespace({
        "dia_mm": ParameterDef(value=dia_mm, unit="mm", bounds=(10.0, 120.0)),
        "height_mm": ParameterDef(value=height_mm, unit="mm", bounds=(3.0, 35.0)),
    })


def test_registered():
    assert "pulley_blank_flat" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("pulley_blank_flat")
    assert sub.name == "pulley_blank_flat"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_volume_matches_hand_computed_cylinder():
    # dia_mm=40 -> radius=20; height_mm=15 -> V = pi * r^2 * h = pi * 400 * 15 = pi * 6000
    p = _ns(dia_mm=40.0, height_mm=15.0)
    v = pulley_blank_flat_module._volume(p)
    expected = math.pi * 6000.0
    assert v == pytest.approx(expected)
    assert v == pytest.approx(18849.5559, abs=1e-3)  # hand-computed literal, not just the formula echoed back


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "pulley_blank_flat")
    v = get_subsystem("pulley_blank_flat").volume_mm3(led)
    assert v > 0.0


def test_volume_matches_hand_computed_at_ledger_defaults(base_ledger, seeded):
    # dia_mm=35.0 default -> radius=17.5; height_mm=10.0 default -> V = pi * 306.25 * 10 = pi * 3062.5
    led = seeded(base_ledger, "pulley_blank_flat")
    v = get_subsystem("pulley_blank_flat").volume_mm3(led)
    assert v == pytest.approx(math.pi * 3062.5)


def test_interfaces_declare_bottom_and_top_at_exact_coordinates():
    sub = get_subsystem_model("pulley_blank_flat")
    assert [i.name for i in sub.interfaces] == ["bottom", "top"]
    p = _ns(dia_mm=40.0, height_mm=15.0)  # half-height = 7.5
    bottom = next(i for i in sub.interfaces if i.name == "bottom").frame(p)
    top = next(i for i in sub.interfaces if i.name == "top").frame(p)
    assert bottom.origin == pytest.approx((0.0, 0.0, -7.5))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 7.5))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "pulley_blank_flat")
    reasons = get_subsystem("pulley_blank_flat").check_invariants(led)
    assert reasons == [], f"pulley_blank_flat default seeds must satisfy invariants: {reasons}"


def test_too_thin_height_violates_min_wall():
    # Deliberately invalid: height_mm=0.5 < the 0.8mm min-wall floor pulley_blank_flat._check enforces.
    p = _ns(dia_mm=40.0, height_mm=0.5)
    reasons = pulley_blank_flat_module._check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_too_thin_height_violates_min_wall_via_ledger(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "pulley_blank_flat", height_mm=(0.5, 0.1, 50))
    reasons = get_subsystem("pulley_blank_flat").check_invariants(led)
    assert any("min wall" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_and_tags(base_ledger, seeded):
    led = seeded(base_ledger, "pulley_blank_flat")
    part = get_subsystem("pulley_blank_flat").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "pulley_blank_flat")
    approx = get_subsystem("pulley_blank_flat").volume_mm3(led)
    real = get_subsystem("pulley_blank_flat").geometry_builder(led).solid.volume
    assert abs(approx - real) / real < 0.01
