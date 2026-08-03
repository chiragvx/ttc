"""Dome nut — sealing dome (blind acorn) structural envelope; a plain solid cylinder body
(`packages/subsystems/dome_nut.py`). Fine cosmetic detail (the actual dome/acorn profile, hex flats)
is deliberately NOT modeled — see that module's docstring."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems import dome_nut
from packages.subsystems.base import Namespace

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(**overrides) -> Namespace:
    """A Namespace built straight from dome_nut's own ParamSpec defaults (no ledger round-trip needed
    for these direct-call tests), with selected params overridden to specific values."""
    sub = get_subsystem_model("dome_nut")
    resolved = {s.name: ParameterDef(value=s.value, unit=s.unit, bounds=(s.min, s.max)) for s in sub.params}
    for name, value in overrides.items():
        pd = resolved[name]
        resolved[name] = ParameterDef(value=value, unit=pd.unit, bounds=pd.bounds)
    return Namespace(resolved)


def test_registered():
    assert "dome_nut" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("dome_nut")
    assert sub.name == "dome_nut"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


# --- volume ------------------------------------------------------------------

def test_volume_matches_hand_computed_cylinder():
    # dia_mm=20 -> radius 10; height_mm=15 -> V = pi * r^2 * h = pi * 100 * 15 = 1500*pi mm^3
    ns = _ns(dia_mm=20.0, height_mm=15.0)
    vol = dome_nut._volume(ns)
    assert vol == pytest.approx(1500.0 * math.pi)
    assert vol == pytest.approx(4712.388980384690)


def test_volume_via_registered_wrapper_matches_same_hand_computed_value(base_ledger, seeded_with):
    # Same case reached through the registered Subsystem -- `get_subsystem("dome_nut").volume_mm3`
    # is a thin ledger-resolving wrapper around this exact module's `_volume` (see
    # `register_subsystem` in packages/subsystems/__init__.py: `sub.volume=_volume`).
    led = seeded_with(base_ledger, "dome_nut", dia_mm=(20.0, 4.0, 30.0), height_mm=(15.0, 3.0, 30.0))
    vol = get_subsystem("dome_nut").volume_mm3(led)
    assert vol == pytest.approx(1500.0 * math.pi)


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "dome_nut")
    assert get_subsystem("dome_nut").volume_mm3(led) > 0.0


# --- invariants ---------------------------------------------------------------

def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "dome_nut")
    reasons = get_subsystem("dome_nut").check_invariants(led)
    assert reasons == [], f"dome_nut default seeds must satisfy invariants: {reasons}"


def test_check_direct_call_flags_height_below_min_wall():
    # Deliberately invalid: height_mm=0.5 trips dome_nut._check's own "< min wall 0.8 mm" rule.
    ns = _ns(height_mm=0.5)
    reasons = dome_nut._check(ns)
    assert reasons != []
    assert any("0.8" in r and "height" in r for r in reasons)


def test_too_thin_height_violates_via_registered_wrapper(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "dome_nut", height_mm=(0.5, 0.1, 30))
    reasons = get_subsystem("dome_nut").check_invariants(led)
    assert any("min wall" in r for r in reasons)


# --- interfaces / mate frames --------------------------------------------------

def test_interfaces_declared_bottom_top():
    sub = get_subsystem_model("dome_nut")
    assert [i.name for i in sub.interfaces] == ["bottom", "top"]


def test_interface_frames_land_at_expected_coordinates():
    # height_mm=15 -> cylinder_end_interfaces places "bottom"/"top" at local Z = -/+ half-height,
    # each normal pointing outward along Z (see base.py::cylinder_end_interfaces).
    ns = _ns(dia_mm=20.0, height_mm=15.0)
    sub = get_subsystem_model("dome_nut")
    frames = {i.name: i.frame(ns) for i in sub.interfaces}
    assert frames["bottom"].origin == pytest.approx((0.0, 0.0, -7.5))
    assert frames["bottom"].normal == pytest.approx((0.0, 0.0, -1.0))
    assert frames["top"].origin == pytest.approx((0.0, 0.0, 7.5))
    assert frames["top"].normal == pytest.approx((0.0, 0.0, 1.0))


# --- real geometry -------------------------------------------------------------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "dome_nut")
    part = get_subsystem("dome_nut").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_matches_real_build_exactly():
    # A plain cylinder — the closed-form _volume must match build123d's own solid volume to a tight
    # tolerance (no lofting/hollowing approximation involved, unlike the curved-body subsystems).
    ns = _ns(dia_mm=20.0, height_mm=15.0)
    part = dome_nut._build(ns)
    real = part.solid.volume
    approx = dome_nut._volume(ns)
    assert real == pytest.approx(approx, rel=1e-6)
