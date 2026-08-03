"""Pulley Blank Timing — new-style subsystem (dedicated bespoke tests).

A plain solid cylinder (timing-pulley teeth NOT modeled — structural envelope only, see
packages/subsystems/pulley_blank_timing.py's module docstring). Exercises `_volume`/`_check`
DIRECTLY (the module's own functions, not just through the `SubsystemContext` adapter
`get_subsystem(...)` wraps them in) plus its `cylinder_end_interfaces` mate frames.
"""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model, pulley_blank_timing
from packages.subsystems.base import resolve_namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "pulley_blank_timing" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("pulley_blank_timing")
    assert sub.name == "pulley_blank_timing"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_volume_matches_hand_computed_cylinder_at_custom_params(base_ledger, seeded_with):
    # dia_mm=40.0 -> radius 20.0, height_mm=15.0: V = pi * r^2 * h = pi * 400 * 15
    led = seeded_with(base_ledger, "pulley_blank_timing", dia_mm=(40.0, 10.0, 100.0), height_mm=(15.0, 3.0, 40.0))
    ns = resolve_namespace(get_subsystem_model("pulley_blank_timing"), led)
    vol = pulley_blank_timing._volume(ns)  # the module's own function, called directly
    assert vol == pytest.approx(math.pi * 20.0 ** 2 * 15.0)
    assert vol == pytest.approx(18849.555921538757)


def test_volume_matches_hand_computed_cylinder_at_defaults(base_ledger, seeded):
    # dia_mm=30.0 (default) -> radius 15.0, height_mm=12.0 (default): V = pi * r^2 * h
    led = seeded(base_ledger, "pulley_blank_timing")
    ns = resolve_namespace(get_subsystem_model("pulley_blank_timing"), led)
    vol = pulley_blank_timing._volume(ns)
    assert vol == pytest.approx(math.pi * 15.0 ** 2 * 12.0)
    assert vol == pytest.approx(8482.300164692441)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "pulley_blank_timing")
    ns = resolve_namespace(get_subsystem_model("pulley_blank_timing"), led)
    assert pulley_blank_timing._check(ns) == []


def test_too_short_violates_min_wall(base_ledger, seeded_with):
    # _check's only rule: height_mm < 0.8 mm min wall -> non-empty violation list
    led = seeded_with(base_ledger, "pulley_blank_timing", height_mm=(0.5, 0.1, 40.0))
    ns = resolve_namespace(get_subsystem_model("pulley_blank_timing"), led)
    reasons = pulley_blank_timing._check(ns)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_cylinder_end_interfaces_declared():
    assert [i.name for i in get_subsystem_model("pulley_blank_timing").interfaces] == ["bottom", "top"]


def test_cylinder_end_interfaces_land_at_exact_coordinates(base_ledger, seeded_with):
    # cylinder_end_interfaces("height_mm") -- bottom/top mount frames sit at +/- height_mm/2 along the
    # blank's own local Z axis (build123d's bd.Cylinder is centered at the origin along Z by default).
    led = seeded_with(base_ledger, "pulley_blank_timing", height_mm=(20.0, 3.0, 40.0))
    model = get_subsystem_model("pulley_blank_timing")
    ns = resolve_namespace(model, led)
    by_name = {i.name: i for i in model.interfaces}
    bottom = by_name["bottom"].frame(ns)
    top = by_name["top"].frame(ns)
    assert bottom.origin == pytest.approx((0.0, 0.0, -10.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 10.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "pulley_blank_timing")
    part = get_subsystem("pulley_blank_timing").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys
