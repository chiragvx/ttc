"""Jaw coupling — one hub blank, a plain solid cylinder (mating jaws/spider not modeled)."""

from __future__ import annotations

import importlib.util
import math
from types import SimpleNamespace

import pytest

import packages.subsystems.jaw_coupling as jaw_coupling
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "jaw_coupling" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("jaw_coupling")
    assert sub.name == "jaw_coupling"
    assert sub.applicable_disciplines == ("structures", "manufacturing", "thermal")
    assert sub.fea_eligible is True


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "jaw_coupling")
    v = get_subsystem("jaw_coupling").volume_mm3(led)
    assert v > 0.0


# --- direct module-level checks (bypassing the ledger plumbing) -------------

def test_volume_matches_hand_computed_cylinder():
    # dia_mm=40, height_mm=32 -> V = pi * r^2 * h = pi * 20^2 * 32 = 12800*pi mm^3
    p = SimpleNamespace(dia_mm=40.0, height_mm=32.0)
    v = jaw_coupling._volume(p)
    assert v == pytest.approx(math.pi * 20.0 ** 2 * 32.0)
    assert v == pytest.approx(12800.0 * math.pi)


def test_interface_frames_land_at_expected_coordinates():
    # cylinder_end_interfaces("height_mm") declares "bottom"/"top" at +/- height/2 on local Z, with
    # outward-pointing normals -- confirmed against _build's un-rotated bd.Cylinder(height=height_mm).
    p = SimpleNamespace(dia_mm=40.0, height_mm=32.0)
    frames = {i.name: i.frame(p) for i in jaw_coupling.JAW_COUPLING.interfaces}
    assert set(frames) == {"bottom", "top"}

    bottom = frames["bottom"]
    assert bottom.origin == pytest.approx((0.0, 0.0, -16.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))

    top = frames["top"]
    assert top.origin == pytest.approx((0.0, 0.0, 16.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


def test_invariants_ok_at_valid_height():
    p = SimpleNamespace(dia_mm=25.0, height_mm=20.0)
    assert jaw_coupling._check(p) == []


def test_invariant_violation_height_too_thin():
    # height_mm=0.5 < the 0.8mm min-wall floor _check enforces -- must trip the existing rule.
    p = SimpleNamespace(dia_mm=25.0, height_mm=0.5)
    reasons = jaw_coupling._check(p)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "jaw_coupling")
    part = get_subsystem("jaw_coupling").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys
