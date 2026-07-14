"""Phase 1 catalog expansion — 15 new subsystems across categories.

Each is validated:
1. Registered under its name.
2. Volume at defaults is positive (mass/print-time telemetry works).
3. Discipline tuple is well-formed.
4. build123d geometry produces a solid with the expected root tag (skipped if b123d missing).
"""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None

# name -> a root tag we expect after the build (guards against silent geometry failures)
PHASE1 = {
    "flat_bar":            "bar.body",
    "square_tube":         "tube.body",
    "dowel_pin":           "pin.body",
    "cover_plate":         "plate.body",
    "t_bar":               "flange.body",
    "z_bracket":           "top.flange",
    "mounting_plate_grid": "plate.body",
    "shaft_collar":        "collar.body",
    "hub":                 "disc.body",
    "threaded_boss":       "boss.body",
    "motor_mount":         "plate.body",
    "hex_nut":             "nut.body",
    "hex_bar":             "bar.body",
    "hex_standoff":        "standoff.body",
}


@pytest.mark.parametrize("name", list(PHASE1))
def test_registered(name):
    assert name in SUBSYSTEM_REGISTRY, f"{name} not registered"
    sub = get_subsystem(name)
    assert sub.name == name
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


@pytest.mark.parametrize("name", list(PHASE1))
def test_positive_volume_at_defaults(base_ledger, seeded, name):
    led = seeded(base_ledger, name)
    v = get_subsystem(name).volume_mm3(led)
    assert v > 0.0, f"{name} default volume must be positive"


@pytest.mark.parametrize("name", list(PHASE1))
def test_invariants_ok_at_defaults(base_ledger, seeded, name):
    led = seeded(base_ledger, name)
    reasons = get_subsystem(name).check_invariants(led)
    assert reasons == [], f"{name} default seeds must satisfy invariants: {reasons}"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
@pytest.mark.parametrize("name,root_tag", list(PHASE1.items()))
def test_geometry_builds(base_ledger, seeded, name, root_tag):
    led = seeded(base_ledger, name)
    part = get_subsystem(name).geometry_builder(led)
    assert part.solid is not None, f"{name} build returned no solid"
    assert root_tag in part.tag_keys, f"{name} missing root tag {root_tag}; got {part.tag_keys}"
