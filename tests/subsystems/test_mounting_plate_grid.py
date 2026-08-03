"""Mounting-plate grid — flat plate with an N×M grid of identical through-holes (chassis mount)."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems.base import Namespace
from packages.subsystems.mounting_plate_grid import _build, _check, _volume

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(**overrides) -> Namespace:
    """A Namespace built from mounting_plate_grid's own ParamSpec defaults, with `overrides` applied
    -- lets tests call the module's `_volume`/`_check`/`_build` directly (no ledger round-trip
    needed), same pattern as test_wing_panel.py's `test_chord_is_monotonic_root_to_tip_not_a_lens`."""
    sub = get_subsystem_model("mounting_plate_grid")
    resolved = {s.name: ParameterDef(value=s.value, unit=s.unit, bounds=(s.min, s.max)) for s in sub.params}
    for name, value in overrides.items():
        pd = resolved[name]
        resolved[name] = ParameterDef(value=value, unit=pd.unit, bounds=pd.bounds)
    return Namespace(resolved)


def test_registered():
    assert "mounting_plate_grid" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("mounting_plate_grid")
    assert sub.name == "mounting_plate_grid"
    assert sub.applicable_disciplines == ("structures", "manufacturing", "thermal")


# --- volume -------------------------------------------------------------------

def test_volume_exact_hand_computed():
    # 100x60x5 plate, a 3x2 grid (6 holes) of 4mm-dia through-holes.
    ns = _ns(width_mm=100.0, height_mm=60.0, thickness_mm=5.0,
             cols=3, rows=2, hole_dia_mm=4.0, hole_spacing_mm=20.0)
    plate_v = 100.0 * 60.0 * 5.0
    hole_v = math.pi * (4.0 / 2.0) ** 2 * 5.0
    expected = plate_v - 6 * hole_v
    assert _volume(ns) == pytest.approx(expected)
    assert _volume(ns) == pytest.approx(30000.0 - 120.0 * math.pi)


def test_volume_at_defaults_matches_ledger_wrapped_call(base_ledger, seeded):
    # cross-check: the ledger-facing volume_mm3() wrapper (packages/subsystems/__init__.py's
    # register_subsystem adapter) must resolve to the EXACT SAME number the module's own _volume()
    # gives when handed the same param values -- not a divergent copy of the formula.
    led = seeded(base_ledger, "mounting_plate_grid")
    assert get_subsystem("mounting_plate_grid").volume_mm3(led) == pytest.approx(_volume(_ns()))


# --- interfaces ---------------------------------------------------------------

def test_declares_top_and_bottom_face_interfaces():
    assert [i.name for i in get_subsystem_model("mounting_plate_grid").interfaces] == ["top", "bottom"]


def test_interface_frames_land_at_exact_plate_face_coordinates():
    # plate_face_interfaces("thickness_mm") (packages/subsystems/base.py) puts "top" at
    # local z=+thickness/2 (normal +Z) and "bottom" at local z=-thickness/2 (normal -Z) -- independent
    # of width/height/hole grid, since the plate is centered on the origin (mounting_plate_grid.py's
    # `_build`, line 24: `bd.Box(width_mm, height_mm, thickness_mm)`).
    ns = _ns(thickness_mm=7.0)
    frames = {i.name: i.frame(ns) for i in get_subsystem_model("mounting_plate_grid").interfaces}
    assert frames["top"].origin == pytest.approx((0.0, 0.0, 3.5))
    assert frames["top"].normal == pytest.approx((0.0, 0.0, 1.0))
    assert frames["bottom"].origin == pytest.approx((0.0, 0.0, -3.5))
    assert frames["bottom"].normal == pytest.approx((0.0, 0.0, -1.0))


# --- invariants -----------------------------------------------------------------

def test_invariants_ok_at_defaults():
    assert _check(_ns()) == []


def test_thin_plate_violates_min_wall():
    ns = _ns(thickness_mm=0.5)  # < _MIN_WALL_MM (0.8mm)
    reasons = _check(ns)
    assert any("min wall" in r for r in reasons)


def test_hole_grid_extends_past_plate_edge_is_flagged():
    # 6 cols at an 80mm pitch span (6-1)*80 + 12 = 412mm on a 40mm-wide plate -- way past the edge.
    ns = _ns(width_mm=40.0, height_mm=40.0, cols=6, rows=2, hole_spacing_mm=80.0, hole_dia_mm=12.0)
    reasons = _check(ns)
    assert any("extends past plate edge" in r for r in reasons)


# --- real geometry ---------------------------------------------------------------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_with_expected_body_and_hole_tags():
    ns = _ns(cols=3, rows=2)
    part = _build(ns)
    assert part.solid is not None
    assert part.solid.is_valid
    assert "plate.body" in part.tag_keys
    expected_hole_tags = {f"hole[{i},{j}].bore" for i in range(3) for j in range(2)}
    assert expected_hole_tags <= part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance():
    ns = _ns()
    approx = _volume(ns)
    real = _build(ns).solid.volume
    rel_err = abs(approx - real) / real
    assert rel_err < 0.02, f"approx {approx:.1f} vs real build {real:.1f} volume (err {rel_err:.1%})"
