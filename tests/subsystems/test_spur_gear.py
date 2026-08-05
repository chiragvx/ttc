"""Spur Gear -- dedicated per-part correctness tests.

Unlike gear_blank/pinion_blank/sprocket_blank (a plain toothless `bd.Cylinder`), this subsystem builds
REAL involute tooth geometry via `py_gearworks.SpurGear` (see spur_gear.py's module docstring for cited
formulas/standards). The `_volume` approximation and the `kind="mesh"` interface radius both key off the
same hand-derivable relation: pitch diameter D = module_mm * tooth_count (ANSI/AGMA 1012-G05 / ISO
21771 gear nomenclature) -- every expected number below for that relation is computed BY HAND from the
formula, not back-filled from this module's own output.

NOTE ON REGISTRATION (cross-agent dependency, see this agent's final report): `spur_gear` is NOT yet
imported by packages/subsystems/__init__.py's side-effect import list (that file is owned by another
part of this session's file-ownership split). Importing `packages.subsystems.spur_gear` directly below
still registers it into the SAME SUBSYSTEM_REGISTRY/SUBSYSTEM_MODELS dicts that module defines (module-
level side effect, identical mechanism every other subsystem file uses) -- so these tests are
self-sufficient regardless of that pending integration step."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems import spur_gear as spur_gear_module  # noqa: F401 -- side-effect registers it
from packages.subsystems.base import Namespace

HAS_PY_GEARWORKS = importlib.util.find_spec("py_gearworks") is not None


def _ns(module_mm: float, tooth_count: float, pressure_angle_deg: float = 20.0,
        face_width_mm: float = 8.0, rpm: float = 3000.0, torque_nmm: float = 500.0) -> Namespace:
    return Namespace({
        "module_mm": ParameterDef(value=module_mm, unit="mm", bounds=(0.3, 6.0)),
        "tooth_count": ParameterDef(value=tooth_count, unit="count", bounds=(6.0, 150.0)),
        "pressure_angle_deg": ParameterDef(value=pressure_angle_deg, unit="deg", bounds=(14.5, 25.0)),
        "face_width_mm": ParameterDef(value=face_width_mm, unit="mm", bounds=(2.0, 100.0)),
        "rpm": ParameterDef(value=rpm, unit="rpm", bounds=(0.0, 20000.0)),
        "torque_nmm": ParameterDef(value=torque_nmm, unit="N*mm", bounds=(0.0, 50000.0)),
    })


def test_registered():
    assert "spur_gear" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("spur_gear")
    assert sub.name == "spur_gear"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_params_present():
    sub = get_subsystem_model("spur_gear")
    names = {p.name for p in sub.params}
    assert names == {"module_mm", "tooth_count", "pressure_angle_deg", "face_width_mm",
                      "rpm", "torque_nmm"}


def test_fea_eligible_is_explicitly_false():
    # NOT a copy-paste of gear_blank's fea_eligible=True -- a real tooth root is a different, harder
    # methodology nobody has validated (see spur_gear.py's module docstring).
    sub = get_subsystem_model("spur_gear")
    assert sub.fea_eligible is False


# --- pitch diameter / mesh interface (hand-derived: D = module_mm * tooth_count) ------------------

def test_mesh_interface_declared_with_pitch_radius_hand_computed():
    # module_mm=2.5, tooth_count=24 -> D = 2.5 * 24 = 60.0 mm -> pitch RADIUS = 30.0 mm (hand-computed
    # before running any code, per the formula cited in spur_gear.py's module docstring).
    sub = get_subsystem_model("spur_gear")
    assert [i.name for i in sub.interfaces] == ["mesh"]
    iface = sub.interfaces[0]
    assert iface.kind == "mesh"
    frame = iface.frame(_ns(module_mm=2.5, tooth_count=24.0))
    assert frame.origin == pytest.approx((0.0, 0.0, 0.0))
    assert frame.normal == pytest.approx((0.0, 0.0, 1.0))
    assert frame.radius == pytest.approx(30.0)


def test_mesh_interface_radius_tracks_module_and_tooth_count_independently():
    # Two more hand-computed points confirm it's genuinely D = m * N, not a cached/stale value:
    # module_mm=1.0, tooth_count=40 -> D = 40 mm -> radius = 20 mm.
    # module_mm=4.0, tooth_count=10 -> D = 40 mm -> radius = 20 mm (SAME diameter, different m/N split).
    iface = get_subsystem_model("spur_gear").interfaces[0]
    a = iface.frame(_ns(module_mm=1.0, tooth_count=40.0))
    b = iface.frame(_ns(module_mm=4.0, tooth_count=10.0))
    assert a.radius == pytest.approx(20.0)
    assert b.radius == pytest.approx(20.0)


def test_mesh_interface_kind_is_mesh_not_mount():
    # placement.py's ordinary coincident-origin mount solver must NOT try to resolve this one.
    iface = get_subsystem_model("spur_gear").interfaces[0]
    assert iface.kind == "mesh"
    assert iface.kind != "mount"


# --- volume (approximate: pitch-diameter cylinder; disclosed simplification) -----------------------

def test_volume_matches_hand_computed_pitch_cylinder():
    # module_mm=2.0, tooth_count=20 -> D=40mm -> pitch radius=20mm; face_width_mm=10 ->
    # V = pi * r^2 * h = pi * 400 * 10 = pi * 4000
    p = _ns(module_mm=2.0, tooth_count=20.0, face_width_mm=10.0)
    v = spur_gear_module._volume(p)
    assert v == pytest.approx(math.pi * 4000.0)
    assert v == pytest.approx(12566.3706, abs=1e-3)  # hand-computed literal, not just the formula echoed back


def test_volume_matches_hand_computed_at_ledger_defaults(base_ledger, seeded):
    # Catalog defaults: module_mm=1.5, tooth_count=20.0 -> D = 1.5*20 = 30mm -> radius=15mm;
    # face_width_mm=8.0 -> V = pi * 225 * 8 = pi * 1800
    led = seeded(base_ledger, "spur_gear")
    v = get_subsystem("spur_gear").volume_mm3(led)
    assert v == pytest.approx(math.pi * 1800.0)
    assert v == pytest.approx(5654.8668, abs=1e-3)  # hand-computed literal


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "spur_gear")
    v = get_subsystem("spur_gear").volume_mm3(led)
    assert v > 0.0


# --- invariants -------------------------------------------------------------------------------------

def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "spur_gear")
    reasons = get_subsystem("spur_gear").check_invariants(led)
    assert reasons == [], f"spur_gear default seeds must satisfy invariants: {reasons}"


def test_too_thin_face_width_violates_min_wall():
    # Deliberately invalid: face_width_mm=0.5 < the 0.8mm min-wall floor spur_gear._check enforces.
    p = _ns(module_mm=1.5, tooth_count=20.0, face_width_mm=0.5)
    reasons = spur_gear_module._check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_check_called_directly_is_clean_at_the_boundary_and_above():
    assert spur_gear_module._check(_ns(1.5, 20.0, face_width_mm=0.8)) == []  # exactly at the floor
    assert spur_gear_module._check(_ns(1.5, 20.0, face_width_mm=8.0)) == []  # catalog default


def test_too_thin_face_width_violates_min_wall_via_ledger(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "spur_gear", face_width_mm=(0.5, 0.1, 50))
    reasons = get_subsystem("spur_gear").check_invariants(led)
    assert any("min wall" in r for r in reasons)


def test_undercut_below_shigley_floor_is_NOT_a_hard_invariant():
    # tooth_count=6 (below Shigley's ~17-18-tooth undercut floor at 20 deg PA cited in spur_gear.py's
    # module docstring) must NOT be rejected here -- py_gearworks models undercut explicitly, so a low
    # tooth count is a real, valid (if suboptimal) geometric choice, not a hard invariant violation.
    # check_invariants reasons are a HARD reject in packages/ledger/apply.py -- this deliberately does
    # not add that hard block; see spur_gear.py's `_check` docstring for the reasoning.
    p = _ns(module_mm=1.5, tooth_count=6.0)
    assert spur_gear_module._check(p) == []


# --- real geometry (needs py_gearworks + build123d -- Linux kernel container only) ------------------
# Convention matched from tests/subsystems/test_gear_blank.py / test_wheel_blank.py (this same
# directory): a module-level HAS_* find_spec guard + @pytest.mark.skipif per test, no separate marker
# registration needed -- correctly skips on this Windows host (neither build123d nor py_gearworks is
# importable here) and, unlike a marker-only gate, actually EXECUTES for real under the "kernel" CI job
# / docker/Dockerfile.dev container, which runs the full suite unfiltered.

@pytest.mark.skipif(not HAS_PY_GEARWORKS, reason="needs py_gearworks (Linux container)")
def test_geometry_builds_and_tags(base_ledger, seeded):
    led = seeded(base_ledger, "spur_gear")
    part = get_subsystem("spur_gear").geometry_builder(led)
    assert part.solid is not None
    assert "gear.body" in part.tag_keys


@pytest.mark.skipif(not HAS_PY_GEARWORKS, reason="needs py_gearworks (Linux container)")
def test_built_gear_has_correct_tooth_count_and_module_tags(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "spur_gear", module_mm=(2.0, 0.3, 6.0), tooth_count=(24.0, 6, 150))
    part = get_subsystem("spur_gear").geometry_builder(led)
    tag = part.tags["gear.body"]
    assert tag["teeth"] == 24
    assert tag["module_mm"] == pytest.approx(2.0)
    assert tag["pitch_dia_mm"] == pytest.approx(48.0)  # D = m*N = 2.0*24


@pytest.mark.skipif(not HAS_PY_GEARWORKS, reason="needs py_gearworks (Linux container)")
def test_real_solid_has_positive_volume_of_the_right_order(base_ledger, seeded):
    # The REAL toothed solid's volume should be within a generous but meaningful band of the disclosed
    # pitch-cylinder APPROXIMATION (spur_gear._volume) -- not exact (teeth aren't a cylinder), but not
    # wildly off either. This is a numerical sanity band, not a hand-derived physics constant.
    led = seeded(base_ledger, "spur_gear")
    approx = get_subsystem("spur_gear").volume_mm3(led)
    real = get_subsystem("spur_gear").geometry_builder(led).solid.volume
    assert real > 0.0
    assert abs(approx - real) / real < 0.25
