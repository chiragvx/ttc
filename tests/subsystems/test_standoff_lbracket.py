"""Standoff + L-bracket subsystems — new-style (Phase C)."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_both_registered():
    assert {"standoff", "lbracket"} <= set(SUBSYSTEM_REGISTRY)
    for n in ("standoff", "lbracket"):
        assert get_subsystem(n).applicable_disciplines == ("structures", "manufacturing", "thermal")


# --- standoff ---------------------------------------------------------------

def test_standoff_volume(base_ledger, seeded):
    led = seeded(base_ledger, "standoff")
    vol = get_subsystem("standoff").volume_mm3(led)
    assert vol == pytest.approx(math.pi * (5.0**2 - 2.0**2) * 15.0)


def test_standoff_seed_defaults_present(base_ledger, seeded):
    led = seeded(base_ledger, "standoff")
    assert "outer_dia_mm" in led.instances["root"].params
    assert led.instances["root"].params["outer_dia_mm"].value == 10.0


def test_standoff_invariant_bore_too_big(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "standoff", inner_dia_mm=(9.5, 1, 30))
    assert any("wall" in r for r in get_subsystem("standoff").check_invariants(led))


# --- L-bracket --------------------------------------------------------------

def test_lbracket_volume(base_ledger, seeded):
    led = seeded(base_ledger, "lbracket")
    vol = get_subsystem("lbracket").volume_mm3(led)
    assert vol == pytest.approx(30.0 * 3.0 * (40.0 + 40.0 - 3.0))


def test_lbracket_invariant_thickness_floor(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lbracket", thickness_mm=(0.5, 0.1, 10))
    assert any("min wall" in r for r in get_subsystem("lbracket").check_invariants(led))


# --- real geometry ----------------------------------------------------------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_standoff_geometry(base_ledger, seeded):
    part = get_subsystem("standoff").geometry_builder(seeded(base_ledger, "standoff"))
    assert part.solid is not None
    assert {"body.cyl", "bore.thru"} <= part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_lbracket_geometry(base_ledger, seeded):
    part = get_subsystem("lbracket").geometry_builder(seeded(base_ledger, "lbracket"))
    assert part.solid is not None
    assert {"leg_a.flange", "leg_b.flange"} <= part.tag_keys
