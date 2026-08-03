"""Cap nut — dedicated per-part correctness tests (bespoke, not just the catalog-wide
parametrized loop in test_subsystems.py).

Hex nut with a domed closed end (dome/hex flats not modeled) — a plain solid cylinder built via
`bd.Cylinder(radius=dia_mm/2, height=height_mm)`, sharing round_post's/longeron's cylinder shape
family and `cylinder_end_interfaces("height_mm")` for its two mount frames (see cap_nut.py)."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems import cap_nut as cap_nut_module
from packages.subsystems.base import Namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(dia_mm: float, height_mm: float) -> Namespace:
    return Namespace({
        "dia_mm": ParameterDef(value=dia_mm, unit="mm", bounds=(4.0, 35.0)),
        "height_mm": ParameterDef(value=height_mm, unit="mm", bounds=(3.0, 35.0)),
    })


def test_registered():
    assert "cap_nut" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("cap_nut")
    assert sub.name == "cap_nut"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_volume_matches_hand_computed_cylinder():
    # dia_mm=12 -> radius=6; height_mm=20 -> V = pi * r^2 * h = pi * 36 * 20 = pi * 720
    p = _ns(dia_mm=12.0, height_mm=20.0)
    v = cap_nut_module._volume(p)
    expected = math.pi * 720.0
    assert v == pytest.approx(expected)
    assert v == pytest.approx(2261.9467, abs=1e-3)  # hand-computed literal, not just the formula echoed back


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "cap_nut")
    v = get_subsystem("cap_nut").volume_mm3(led)
    assert v > 0.0


def test_volume_matches_hand_computed_at_ledger_defaults(base_ledger, seeded):
    # dia_mm=10.0 default -> radius=5; height_mm=10.0 default -> V = pi * 25 * 10 = pi * 250
    led = seeded(base_ledger, "cap_nut")
    v = get_subsystem("cap_nut").volume_mm3(led)
    assert v == pytest.approx(math.pi * 250.0)


def test_interfaces_declare_bottom_and_top_at_exact_coordinates():
    sub = get_subsystem_model("cap_nut")
    assert [i.name for i in sub.interfaces] == ["bottom", "top"]
    p = _ns(dia_mm=12.0, height_mm=20.0)  # half-height = 10.0
    bottom = next(i for i in sub.interfaces if i.name == "bottom").frame(p)
    top = next(i for i in sub.interfaces if i.name == "top").frame(p)
    assert bottom.origin == pytest.approx((0.0, 0.0, -10.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 10.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "cap_nut")
    reasons = get_subsystem("cap_nut").check_invariants(led)
    assert reasons == [], f"cap_nut default seeds must satisfy invariants: {reasons}"


def test_too_thin_height_violates_min_wall():
    # Deliberately invalid: height_mm=0.5 < the 0.8mm min-wall floor cap_nut._check enforces.
    p = _ns(dia_mm=12.0, height_mm=0.5)
    reasons = cap_nut_module._check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_too_thin_height_violates_min_wall_via_ledger(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "cap_nut", height_mm=(0.5, 0.1, 50))
    reasons = get_subsystem("cap_nut").check_invariants(led)
    assert any("min wall" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_and_tags(base_ledger, seeded):
    led = seeded(base_ledger, "cap_nut")
    part = get_subsystem("cap_nut").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "cap_nut")
    approx = get_subsystem("cap_nut").volume_mm3(led)
    real = get_subsystem("cap_nut").geometry_builder(led).solid.volume
    assert abs(approx - real) / real < 0.01
