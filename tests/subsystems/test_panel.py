"""Panel / faceplate subsystem — bespoke tests (2026-07-31). No dedicated test file existed for
`panel` before this one (only the generic catalog-wide parametrized loop covered it) — see
packages/subsystems/panel.py for the plate-with-window-and-4-corner-holes geometry this exercises."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems.panel import _check, _volume


def test_registered_with_expected_disciplines():
    assert "panel" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("panel")
    assert sub.name == "panel"
    assert sub.applicable_disciplines == ("structures", "manufacturing", "thermal")


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "panel")
    assert get_subsystem("panel").check_invariants(led) == []


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "panel")
    assert get_subsystem("panel").volume_mm3(led) > 0.0


# --- hand-computed volume ----------------------------------------------------

def test_volume_hand_computed_against_module_function():
    # 120 x 90 x 4 mm plate, 60 x 40 mm window, 4x 5.0 mm-dia corner holes, all through-thickness.
    p = SimpleNamespace(width_mm=120.0, height_mm=90.0, thickness_mm=4.0,
                        window_width_mm=60.0, window_height_mm=40.0, hole_dia_mm=5.0)
    plate = 120.0 * 90.0 * 4.0                        # 43200.0 mm^3
    window = 60.0 * 40.0 * 4.0                         # 9600.0 mm^3
    holes = 4 * math.pi * (5.0 / 2.0) ** 2 * 4.0        # 100*pi mm^3
    expected = plate - window - holes                  # 33600 - 100*pi
    assert expected == pytest.approx(33600.0 - 100.0 * math.pi)
    assert _volume(p) == pytest.approx(expected)


def test_volume_clamps_at_zero_when_cutouts_exceed_plate():
    # Deliberately absurd (window + holes bigger than the plate itself) — _volume must clamp to 0.0,
    # never go negative, regardless of what check_invariants would say about these same params.
    p = SimpleNamespace(width_mm=10.0, height_mm=10.0, thickness_mm=1.0,
                        window_width_mm=250.0, window_height_mm=250.0, hole_dia_mm=10.0)
    assert _volume(p) == 0.0


# --- exposed mate frames (plate_face_interfaces("thickness_mm")) ------------

def test_face_interfaces_declared_top_and_bottom():
    assert [i.name for i in get_subsystem_model("panel").interfaces] == ["top", "bottom"]


def test_face_interfaces_land_at_exact_thickness_offset():
    p = SimpleNamespace(thickness_mm=4.0)
    interfaces = {i.name: i for i in get_subsystem_model("panel").interfaces}
    top = interfaces["top"].frame(p)
    bottom = interfaces["bottom"].frame(p)
    assert top.origin == (0.0, 0.0, 2.0)   # +half-thickness, outward normal +Z
    assert top.normal == (0.0, 0.0, 1.0)
    assert bottom.origin == (0.0, 0.0, -2.0)  # -half-thickness, outward normal -Z
    assert bottom.normal == (0.0, 0.0, -1.0)


# --- invariants: at least one deliberately-invalid combo must trip a rule ---

def test_invariant_thickness_below_min_wall():
    p = SimpleNamespace(width_mm=100.0, height_mm=80.0, thickness_mm=0.5,
                        window_width_mm=60.0, window_height_mm=40.0, hole_dia_mm=4.0)
    reasons = _check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_invariant_window_too_wide_for_frame():
    # width_mm=100 leaves only 100 - 2*8 = 84 mm before the 8 mm-per-side frame rule trips.
    p = SimpleNamespace(width_mm=100.0, height_mm=80.0, thickness_mm=3.0,
                        window_width_mm=90.0, window_height_mm=40.0, hole_dia_mm=4.0)
    reasons = _check(p)
    assert reasons != []
    assert any("window_width" in r for r in reasons)


def test_invariant_window_too_tall_for_frame():
    # height_mm=80 leaves only 80 - 2*8 = 64 mm before the 8 mm-per-side frame rule trips.
    p = SimpleNamespace(width_mm=100.0, height_mm=80.0, thickness_mm=3.0,
                        window_width_mm=60.0, window_height_mm=70.0, hole_dia_mm=4.0)
    reasons = _check(p)
    assert reasons != []
    assert any("window_height" in r for r in reasons)
