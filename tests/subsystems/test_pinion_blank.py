"""Pinion Blank — new-style subsystem (dedicated bespoke tests).

A plain solid cylinder (gear/sprocket teeth NOT modeled — structural envelope only, see
packages/subsystems/pinion_blank.py's module docstring). Exercises `_volume`/`_check` DIRECTLY (the
module's own functions, not just through the `SubsystemContext` adapter `get_subsystem(...)` wraps
them in) plus its `cylinder_end_interfaces` mate frames.
"""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model, pinion_blank
from packages.subsystems.base import resolve_namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "pinion_blank" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("pinion_blank")
    assert sub.name == "pinion_blank"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_volume_matches_hand_computed_cylinder_at_custom_params(base_ledger, seeded_with):
    # dia_mm=18.0 -> radius 9.0, height_mm=12.0: V = pi * r^2 * h = pi * 81 * 12
    led = seeded_with(base_ledger, "pinion_blank", dia_mm=(18.0, 5.0, 50.0), height_mm=(12.0, 2.0, 25.0))
    ns = resolve_namespace(get_subsystem_model("pinion_blank"), led)
    vol = pinion_blank._volume(ns)  # the module's own function, called directly
    assert vol == pytest.approx(math.pi * 9.0 ** 2 * 12.0)
    assert vol == pytest.approx(3053.628059289279)


def test_volume_matches_hand_computed_cylinder_at_defaults(base_ledger, seeded):
    # dia_mm=15.0 (default) -> radius 7.5, height_mm=8.0 (default): V = pi * r^2 * h
    led = seeded(base_ledger, "pinion_blank")
    ns = resolve_namespace(get_subsystem_model("pinion_blank"), led)
    vol = pinion_blank._volume(ns)
    assert vol == pytest.approx(math.pi * 7.5 ** 2 * 8.0)
    assert vol == pytest.approx(1413.7166941154069)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "pinion_blank")
    ns = resolve_namespace(get_subsystem_model("pinion_blank"), led)
    assert pinion_blank._check(ns) == []


def test_too_short_violates_min_wall(base_ledger, seeded_with):
    # _check's only rule: height_mm < 0.8 mm min wall -> non-empty violation list
    led = seeded_with(base_ledger, "pinion_blank", height_mm=(0.5, 0.1, 25.0))
    ns = resolve_namespace(get_subsystem_model("pinion_blank"), led)
    reasons = pinion_blank._check(ns)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_cylinder_end_interfaces_declared():
    assert [i.name for i in get_subsystem_model("pinion_blank").interfaces] == ["bottom", "top"]


def test_cylinder_end_interfaces_land_at_exact_coordinates(base_ledger, seeded_with):
    # cylinder_end_interfaces("height_mm") -- bottom/top mount frames sit at +/- height_mm/2 along the
    # blank's own local Z axis (build123d's bd.Cylinder is centered at the origin along Z by default).
    led = seeded_with(base_ledger, "pinion_blank", height_mm=(16.0, 2.0, 25.0))
    model = get_subsystem_model("pinion_blank")
    ns = resolve_namespace(model, led)
    by_name = {i.name: i for i in model.interfaces}
    bottom = by_name["bottom"].frame(ns)
    top = by_name["top"].frame(ns)
    assert bottom.origin == pytest.approx((0.0, 0.0, -8.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 8.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "pinion_blank")
    part = get_subsystem("pinion_blank").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys
