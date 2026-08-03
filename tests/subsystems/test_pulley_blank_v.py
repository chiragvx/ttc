"""Pulley Blank V — new-style subsystem (dedicated bespoke tests).

A plain solid cylinder (V-groove NOT modeled — structural envelope only, see
packages/subsystems/pulley_blank_v.py's module docstring). Exercises `_volume`/`_check` DIRECTLY (the
module's own functions, not just through the `SubsystemContext` adapter `get_subsystem(...)` wraps
them in) plus its `cylinder_end_interfaces` mate frames. Same shape family/construction as
pinion_blank.py (`bd.Cylinder(radius=dia_mm/2, height=height_mm)`, centered at the origin) --
mirrors that file's dedicated test structure.
"""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model, pulley_blank_v
from packages.subsystems.base import resolve_namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "pulley_blank_v" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("pulley_blank_v")
    assert sub.name == "pulley_blank_v"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_volume_matches_hand_computed_cylinder_at_custom_params(base_ledger, seeded_with):
    # dia_mm=40.0 -> radius 20.0, height_mm=18.0: V = pi * r^2 * h = pi * 400 * 18
    led = seeded_with(base_ledger, "pulley_blank_v", dia_mm=(40.0, 10.0, 120.0), height_mm=(18.0, 3.0, 40.0))
    ns = resolve_namespace(get_subsystem_model("pulley_blank_v"), led)
    vol = pulley_blank_v._volume(ns)  # the module's own function, called directly
    assert vol == pytest.approx(math.pi * 20.0 ** 2 * 18.0)
    assert vol == pytest.approx(22619.46710584651)


def test_volume_matches_hand_computed_cylinder_at_defaults(base_ledger, seeded):
    # dia_mm=35.0 (default) -> radius 17.5, height_mm=12.0 (default): V = pi * r^2 * h
    led = seeded(base_ledger, "pulley_blank_v")
    ns = resolve_namespace(get_subsystem_model("pulley_blank_v"), led)
    vol = pulley_blank_v._volume(ns)
    assert vol == pytest.approx(math.pi * 17.5 ** 2 * 12.0)
    assert vol == pytest.approx(11545.35300194249)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "pulley_blank_v")
    ns = resolve_namespace(get_subsystem_model("pulley_blank_v"), led)
    assert pulley_blank_v._check(ns) == []


def test_too_short_violates_min_wall(base_ledger, seeded_with):
    # _check's only rule: height_mm < 0.8 mm min wall -> non-empty violation list
    led = seeded_with(base_ledger, "pulley_blank_v", height_mm=(0.5, 0.1, 40.0))
    ns = resolve_namespace(get_subsystem_model("pulley_blank_v"), led)
    reasons = pulley_blank_v._check(ns)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_check_called_directly_flags_too_thin_height():
    # exact boundary from the source: `if p.height_mm < 0.8: return [f"height {p.height_mm:.2f} mm <
    # min wall 0.8 mm"]` -- dia_mm plays no part in this rule, only height_mm trips it.
    from packages.ledger.parameter import ParameterDef
    from packages.subsystems.base import Namespace
    ns = Namespace({
        "dia_mm": ParameterDef(value=35.0, unit="mm", bounds=(10.0, 120.0)),
        "height_mm": ParameterDef(value=0.5, unit="mm", bounds=(3.0, 40.0)),
    })
    assert pulley_blank_v._check(ns) == ["height 0.50 mm < min wall 0.8 mm"]


def test_cylinder_end_interfaces_declared():
    assert [i.name for i in get_subsystem_model("pulley_blank_v").interfaces] == ["bottom", "top"]


def test_cylinder_end_interfaces_land_at_exact_coordinates(base_ledger, seeded_with):
    # cylinder_end_interfaces("height_mm") -- bottom/top mount frames sit at +/- height_mm/2 along the
    # blank's own local Z axis (build123d's bd.Cylinder is centered at the origin along Z by default).
    led = seeded_with(base_ledger, "pulley_blank_v", height_mm=(24.0, 3.0, 40.0))
    model = get_subsystem_model("pulley_blank_v")
    ns = resolve_namespace(model, led)
    by_name = {i.name: i for i in model.interfaces}
    bottom = by_name["bottom"].frame(ns)
    top = by_name["top"].frame(ns)
    assert bottom.origin == pytest.approx((0.0, 0.0, -12.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 12.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


def test_end_interfaces_track_a_non_default_height(base_ledger, seeded_with):
    # The frame is a CALLABLE over resolved params, not a cached constant -- changing height_mm must
    # move both interfaces with it (dia_mm plays no part in either end's coordinates).
    led = seeded_with(base_ledger, "pulley_blank_v", height_mm=(30.0, 3.0, 40.0))
    model = get_subsystem_model("pulley_blank_v")
    ns = resolve_namespace(model, led)
    by_name = {i.name: i for i in model.interfaces}
    assert by_name["bottom"].frame(ns).origin == pytest.approx((0.0, 0.0, -15.0))
    assert by_name["top"].frame(ns).origin == pytest.approx((0.0, 0.0, 15.0))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "pulley_blank_v")
    part = get_subsystem("pulley_blank_v").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys
