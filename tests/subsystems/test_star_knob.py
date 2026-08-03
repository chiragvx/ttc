"""Star Knob — new-style subsystem (dedicated bespoke tests).

A plain solid cylinder (star-shape lobes NOT modeled — structural envelope only, see
packages/subsystems/star_knob.py's module docstring). Exercises `_volume`/`_check` DIRECTLY (the
module's own functions, not just through the `SubsystemContext` adapter `get_subsystem(...)` wraps
them in) plus its `cylinder_end_interfaces` mate frames.
"""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model, star_knob
from packages.subsystems.base import resolve_namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "star_knob" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("star_knob")
    assert sub.name == "star_knob"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_volume_matches_hand_computed_cylinder_at_custom_params(base_ledger, seeded_with):
    # dia_mm=20.0 -> radius 10.0, height_mm=10.0: V = pi * r^2 * h = pi * 100 * 10
    led = seeded_with(base_ledger, "star_knob", dia_mm=(20.0, 10.0, 100.0), height_mm=(10.0, 4.0, 45.0))
    ns = resolve_namespace(get_subsystem_model("star_knob"), led)
    vol = star_knob._volume(ns)  # the module's own function, called directly
    assert vol == pytest.approx(math.pi * 10.0 ** 2 * 10.0)
    assert vol == pytest.approx(3141.5926535897934)


def test_volume_matches_hand_computed_cylinder_at_defaults(base_ledger, seeded):
    # dia_mm=35.0 (default) -> radius 17.5, height_mm=15.0 (default): V = pi * r^2 * h
    led = seeded(base_ledger, "star_knob")
    ns = resolve_namespace(get_subsystem_model("star_knob"), led)
    vol = star_knob._volume(ns)
    assert vol == pytest.approx(math.pi * 17.5 ** 2 * 15.0)
    assert vol == pytest.approx(14431.691252428112)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "star_knob")
    ns = resolve_namespace(get_subsystem_model("star_knob"), led)
    assert star_knob._check(ns) == []


def test_too_short_violates_min_wall(base_ledger, seeded_with):
    # _check's only rule: height_mm < 0.8 mm min wall -> non-empty violation list
    led = seeded_with(base_ledger, "star_knob", height_mm=(0.5, 0.1, 45.0))
    ns = resolve_namespace(get_subsystem_model("star_knob"), led)
    reasons = star_knob._check(ns)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_check_called_directly_is_clean_at_the_boundary_and_above():
    from packages.subsystems.base import Namespace
    from packages.ledger.parameter import ParameterDef

    def _ns(dia_mm: float, height_mm: float):
        return Namespace({
            "dia_mm": ParameterDef(value=dia_mm, unit="mm", bounds=(10.0, 100.0)),
            "height_mm": ParameterDef(value=height_mm, unit="mm", bounds=(4.0, 45.0)),
        })

    assert star_knob._check(_ns(dia_mm=35.0, height_mm=0.8)) == []  # exactly at the floor -- not "< 0.8"
    assert star_knob._check(_ns(dia_mm=35.0, height_mm=15.0)) == []  # catalog default


def test_cylinder_end_interfaces_declared():
    assert [i.name for i in get_subsystem_model("star_knob").interfaces] == ["bottom", "top"]


def test_cylinder_end_interfaces_land_at_exact_coordinates(base_ledger, seeded_with):
    # cylinder_end_interfaces("height_mm") -- bottom/top mount frames sit at +/- height_mm/2 along the
    # knob's own local Z axis (build123d's bd.Cylinder is centered at the origin along Z by default).
    led = seeded_with(base_ledger, "star_knob", height_mm=(20.0, 4.0, 45.0))
    model = get_subsystem_model("star_knob")
    ns = resolve_namespace(model, led)
    by_name = {i.name: i for i in model.interfaces}
    bottom = by_name["bottom"].frame(ns)
    top = by_name["top"].frame(ns)
    assert bottom.origin == pytest.approx((0.0, 0.0, -10.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 10.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


def test_end_interfaces_track_a_non_default_height(base_ledger, seeded_with):
    # The frame is a CALLABLE over resolved params, not a cached constant -- changing height_mm must
    # move both interfaces with it (dia_mm plays no part in either end's coordinates).
    led = seeded_with(base_ledger, "star_knob", height_mm=(40.0, 4.0, 45.0))
    model = get_subsystem_model("star_knob")
    ns = resolve_namespace(model, led)
    by_name = {i.name: i for i in model.interfaces}
    assert by_name["bottom"].frame(ns).origin == pytest.approx((0.0, 0.0, -20.0))
    assert by_name["top"].frame(ns).origin == pytest.approx((0.0, 0.0, 20.0))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "star_knob")
    part = get_subsystem("star_knob").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys
