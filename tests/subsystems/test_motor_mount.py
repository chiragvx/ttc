"""Motor mount — square plate + 4 corner bolt holes + a central shaft-clearance bore
(packages/subsystems/motor_mount.py).

Bespoke per-part correctness test (the generic catalog-wide parametrized loop in
test_subsystems.py only proves every registered subsystem BUILDS — it asserts no per-part
numbers). Here we hand-compute the expected volume and mate-frame coordinates for specific
parameter values and check them against the module's own _volume()/_check() functions and its
declared plate_face_interfaces() mate frames directly."""

from __future__ import annotations

import importlib.util
import math
from types import SimpleNamespace

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems.motor_mount import _MIN_WALL_MM, _check, _volume

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "motor_mount" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("motor_mount")
    assert sub.name == "motor_mount"
    assert sub.description == "Square motor mount — 4 corner bolts + central shaft bore"
    assert sub.applicable_disciplines == ("structures", "manufacturing", "thermal")
    assert sub.fea_eligible is True


def test_declares_top_bottom_face_interfaces():
    # plate_face_interfaces("thickness_mm") -- confirmed by direct code reading.
    assert [i.name for i in get_subsystem_model("motor_mount").interfaces] == ["top", "bottom"]


# --- volume: hand-computed, checked against the module's own _volume() called directly ---------

def test_volume_matches_hand_computed_formula_at_custom_params():
    p = SimpleNamespace(
        plate_size_mm=50.0, thickness_mm=6.0, bolt_pattern_mm=40.0,
        bolt_hole_dia_mm=4.0, center_bore_dia_mm=20.0,
    )
    vol = _volume(p)
    # hand-computed: a 50x50x6mm block, minus the dia-20 center bore, minus 4 dia-4 corner holes,
    # all cut clean through a 6mm-thick plate.
    body = 50.0 * 50.0 * 6.0
    center = math.pi * (20.0 / 2.0) ** 2 * 6.0
    bolts = 4 * math.pi * (4.0 / 2.0) ** 2 * 6.0
    expected = body - center - bolts
    assert vol == pytest.approx(expected)
    assert vol == pytest.approx(12813.451513101503)  # pinned hand-computed value


def test_volume_floors_at_zero_when_bores_would_exceed_the_block():
    # _volume's max(0.0, ...) safety net -- absurdly large bores relative to a tiny plate.
    p = SimpleNamespace(
        plate_size_mm=5.0, thickness_mm=1.0, bolt_pattern_mm=5.0,
        bolt_hole_dia_mm=20.0, center_bore_dia_mm=20.0,
    )
    assert _volume(p) == 0.0


def test_volume_via_ledger_matches_hand_computed_defaults(base_ledger, seeded):
    # cross-check the normal ledger-facing path (used by the rest of the codebase) against the
    # registered defaults (plate_size_mm=42, thickness_mm=5, bolt_hole_dia_mm=3.4, center_bore_dia_mm=22).
    led = seeded(base_ledger, "motor_mount")
    vol = get_subsystem("motor_mount").volume_mm3(led)
    body = 42.0 * 42.0 * 5.0
    center = math.pi * 11.0 ** 2 * 5.0
    bolts = 4 * math.pi * 1.7 ** 2 * 5.0
    assert vol == pytest.approx(body - center - bolts)


# --- mate frame: top/bottom faces, exact coordinates from the declared interface ----------------

def test_top_bottom_mate_frames_land_at_exact_coordinates():
    p = SimpleNamespace(thickness_mm=6.0)
    interfaces = {i.name: i for i in get_subsystem_model("motor_mount").interfaces}
    top = interfaces["top"].frame(p)
    bottom = interfaces["bottom"].frame(p)
    assert top.origin == pytest.approx((0.0, 0.0, 3.0))       # +half-thickness
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))
    assert bottom.origin == pytest.approx((0.0, 0.0, -3.0))   # -half-thickness
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))


# --- invariants: at least one deliberately-invalid combo must trip a real rule ------------------

def test_invariants_clean_at_registered_defaults():
    p = SimpleNamespace(
        plate_size_mm=42.0, thickness_mm=5.0, bolt_pattern_mm=31.0,
        bolt_hole_dia_mm=3.4, center_bore_dia_mm=22.0,
    )
    assert _check(p) == []


def test_invariant_violation_thickness_below_min_wall():
    p = SimpleNamespace(
        plate_size_mm=42.0, thickness_mm=0.5, bolt_pattern_mm=31.0,
        bolt_hole_dia_mm=3.4, center_bore_dia_mm=22.0,
    )
    assert 0.5 < _MIN_WALL_MM  # sanity: this really is below the floor being tested
    reasons = _check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_invariant_violation_center_bore_too_large_for_plate():
    # center_bore_dia_mm >= plate_size_mm - 2*_MIN_WALL_MM (42 - 1.6 = 40.4) -- 42.0 trips it.
    threshold = 42.0 - 2 * _MIN_WALL_MM
    p = SimpleNamespace(
        plate_size_mm=42.0, thickness_mm=5.0, bolt_pattern_mm=31.0,
        bolt_hole_dia_mm=3.4, center_bore_dia_mm=42.0,
    )
    assert p.center_bore_dia_mm >= threshold  # sanity: this really is over the threshold
    reasons = _check(p)
    assert reasons != []
    assert any("center bore too large" in r for r in reasons)


def test_invariant_violation_bolt_pattern_falls_off_corners():
    # bolt_pattern_mm >= plate_size_mm*sqrt(2) - 2*bolt_hole_dia_mm (~52.6 for these params).
    threshold = 42.0 * math.sqrt(2.0) - 2 * 3.4
    p = SimpleNamespace(
        plate_size_mm=42.0, thickness_mm=5.0, bolt_pattern_mm=60.0,
        bolt_hole_dia_mm=3.4, center_bore_dia_mm=22.0,
    )
    assert p.bolt_pattern_mm >= threshold  # sanity: this really is over the threshold
    reasons = _check(p)
    assert reasons != []
    assert any("bolt pattern falls off" in r for r in reasons)


def test_invariants_via_ledger_seeded_with_matches_direct_call(base_ledger, seeded_with):
    # cross-check the ledger-facing path (used by the rest of the codebase) against the direct-call
    # thickness-floor rule verified above.
    led = seeded_with(base_ledger, "motor_mount", thickness_mm=(0.5, 0.1, 10.0))
    reasons = get_subsystem("motor_mount").check_invariants(led)
    assert any("min wall" in r for r in reasons)


# --- real geometry: _build()'s own tags land at the exact hand-computed coordinates -------------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_build_tags_land_at_hand_computed_coordinates(base_ledger, seeded_with):
    led = seeded_with(
        base_ledger, "motor_mount",
        plate_size_mm=(50.0, 20.0, 200.0), thickness_mm=(6.0, 1.0, 15.0),
        bolt_pattern_mm=(40.0, 10.0, 180.0), bolt_hole_dia_mm=(4.0, 2.0, 10.0),
        center_bore_dia_mm=(20.0, 3.0, 100.0),
    )
    part = get_subsystem("motor_mount").geometry_builder(led)
    assert part.solid is not None
    assert len(list(part.solid.solids())) == 1  # single connected manifold body
    assert {"plate.body", "center.bore",
            "bolt[0].bore", "bolt[1].bore", "bolt[2].bore", "bolt[3].bore"} <= part.tag_keys

    assert part.tags["plate.body"]["size"] == [50.0, 50.0, 6.0]
    assert part.tags["center.bore"]["dia"] == 20.0

    off = 40.0 / 2.0 / math.sqrt(2.0)  # ~14.142mm, half the bolt pattern projected onto each axis
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
        cx, cy = part.tags[f"bolt[{i}].bore"]["center"]
        assert cx == pytest.approx(sx * off)
        assert cy == pytest.approx(sy * off)
        assert part.tags[f"bolt[{i}].bore"]["dia"] == 4.0
