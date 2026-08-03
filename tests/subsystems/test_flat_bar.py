"""Flat bar — solid rectangular bar (a structural section)."""

from __future__ import annotations

import importlib.util

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems.base import Namespace
from packages.subsystems.flat_bar import _check, _volume

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(**overrides) -> Namespace:
    """A bare Namespace over flat_bar's own params, bypassing the ledger entirely — for exercising
    `_volume`/`_check`/the interface frames directly against hand-computed values."""
    values = {"length_mm": 100.0, "width_mm": 20.0, "thickness_mm": 5.0}
    values.update(overrides)
    return Namespace({k: ParameterDef(value=v, unit="mm", bounds=(0.0, 10_000.0)) for k, v in values.items()})


def test_registered():
    assert "flat_bar" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("flat_bar")
    assert sub.name == "flat_bar"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "flat_bar")
    v = get_subsystem("flat_bar").volume_mm3(led)
    assert v > 0.0


def test_volume_matches_box_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "flat_bar")
    v = get_subsystem("flat_bar").volume_mm3(led)
    assert v == pytest.approx(100.0 * 20.0 * 5.0)


def test_volume_hand_computed_calling_module_function_directly():
    # 150 x 30 x 6 mm bar -> 27000 mm^3, hand-computed independently of the ledger/wrapper path.
    p = _ns(length_mm=150.0, width_mm=30.0, thickness_mm=6.0)
    assert _volume(p) == pytest.approx(150.0 * 30.0 * 6.0)
    assert _volume(p) == pytest.approx(27000.0)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "flat_bar")
    reasons = get_subsystem("flat_bar").check_invariants(led)
    assert reasons == [], f"flat_bar default seeds must satisfy invariants: {reasons}"


def test_too_thin_violates_min_wall_calling_module_function_directly():
    # _MIN_WALL_MM = 0.8 in flat_bar.py; thickness_mm=0.5 must trip that exact rule.
    p = _ns(thickness_mm=0.5)
    reasons = _check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_too_thin_violates_min_wall_via_ledger(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "flat_bar", thickness_mm=(0.5, 0.1, 30))
    reasons = get_subsystem("flat_bar").check_invariants(led)
    assert any("min wall" in r for r in reasons)


def test_end_interfaces_land_at_expected_coordinates():
    # bar_end_interfaces("length_mm") (packages/subsystems/base.py) places end_a/end_b at +/-
    # length_mm/2 on local X with outward-pointing normals along X -- confirmed against flat_bar's
    # own bd.Box(length_mm, width_mm, thickness_mm) build, centered at the origin.
    sub = get_subsystem_model("flat_bar")
    assert [i.name for i in sub.interfaces] == ["end_a", "end_b"]
    end_a, end_b = sub.interfaces

    p = _ns(length_mm=150.0, width_mm=30.0, thickness_mm=6.0)
    frame_a = end_a.frame(p)
    frame_b = end_b.frame(p)

    assert frame_a.origin == pytest.approx((-75.0, 0.0, 0.0))
    assert frame_a.normal == pytest.approx((-1.0, 0.0, 0.0))
    assert frame_b.origin == pytest.approx((75.0, 0.0, 0.0))
    assert frame_b.normal == pytest.approx((1.0, 0.0, 0.0))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "flat_bar")
    part = get_subsystem("flat_bar").geometry_builder(led)
    assert part.solid is not None
    assert "bar.body" in part.tag_keys
