"""Hex Knob — new-style subsystem (dedicated bespoke tests).

A plain solid cylinder (hex flats NOT modeled — structural envelope only, see
packages/subsystems/hex_knob.py's module docstring). Exercises `_volume`/`_check` DIRECTLY (the
module's own functions, not just through the `SubsystemContext` adapter `get_subsystem(...)` wraps
them in) plus its `cylinder_end_interfaces` mate frames.
"""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model, hex_knob
from packages.subsystems.base import resolve_namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "hex_knob" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("hex_knob")
    assert sub.name == "hex_knob"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_volume_matches_hand_computed_cylinder_at_custom_params(base_ledger, seeded_with):
    # dia_mm=20.0 -> radius 10.0, height_mm=10.0: V = pi * r^2 * h = pi * 100 * 10
    led = seeded_with(base_ledger, "hex_knob", dia_mm=(20.0, 8.0, 80.0), height_mm=(10.0, 4.0, 45.0))
    ns = resolve_namespace(get_subsystem_model("hex_knob"), led)
    vol = hex_knob._volume(ns)  # the module's own function, called directly
    assert vol == pytest.approx(math.pi * 10.0 ** 2 * 10.0)
    assert vol == pytest.approx(3141.592653589793)


def test_volume_matches_hand_computed_cylinder_at_defaults(base_ledger, seeded):
    # dia_mm=25.0 (default) -> radius 12.5, height_mm=15.0 (default): V = pi * r^2 * h
    led = seeded(base_ledger, "hex_knob")
    ns = resolve_namespace(get_subsystem_model("hex_knob"), led)
    vol = hex_knob._volume(ns)
    assert vol == pytest.approx(math.pi * 12.5 ** 2 * 15.0)
    assert vol == pytest.approx(7363.107215273689)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "hex_knob")
    ns = resolve_namespace(get_subsystem_model("hex_knob"), led)
    assert hex_knob._check(ns) == []


def test_too_short_violates_min_wall(base_ledger, seeded_with):
    # _check's only rule: height_mm < 0.8 mm min wall -> non-empty violation list
    led = seeded_with(base_ledger, "hex_knob", height_mm=(0.5, 0.1, 45.0))
    ns = resolve_namespace(get_subsystem_model("hex_knob"), led)
    reasons = hex_knob._check(ns)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_cylinder_end_interfaces_declared():
    assert [i.name for i in get_subsystem_model("hex_knob").interfaces] == ["bottom", "top"]


def test_cylinder_end_interfaces_land_at_exact_coordinates(base_ledger, seeded_with):
    # cylinder_end_interfaces("height_mm") -- bottom/top mount frames sit at +/- height_mm/2 along the
    # knob's own local Z axis (build123d's bd.Cylinder is centered at the origin along Z by default).
    led = seeded_with(base_ledger, "hex_knob", height_mm=(20.0, 4.0, 45.0))
    model = get_subsystem_model("hex_knob")
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
    led = seeded(base_ledger, "hex_knob")
    part = get_subsystem("hex_knob").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys
