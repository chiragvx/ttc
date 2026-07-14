"""U-channel, panel/faceplate, and washer — new-style (Phase B/C)."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_all_three_registered():
    assert {"uchannel", "panel", "washer"} <= set(SUBSYSTEM_REGISTRY)


# --- volumes ----------------------------------------------------------------

def test_uchannel_volume(base_ledger, seeded):
    led = seeded(base_ledger, "uchannel")
    v = get_subsystem("uchannel").volume_mm3(led)
    assert v == pytest.approx(80 * 40 * 25 - 80 * (40 - 6) * (25 - 3))


def test_panel_volume(base_ledger, seeded):
    led = seeded(base_ledger, "panel")
    v = get_subsystem("panel").volume_mm3(led)
    expect = 100 * 80 * 3 - 60 * 40 * 3 - 4 * math.pi * (2.0**2) * 3
    assert v == pytest.approx(expect)


def test_washer_volume(base_ledger, seeded):
    led = seeded(base_ledger, "washer")
    v = get_subsystem("washer").volume_mm3(led)
    assert v == pytest.approx(math.pi * (10.0**2 - 4.0**2) * 2.0)


# --- invariants -------------------------------------------------------------

def test_uchannel_no_channel(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "uchannel",
                     width_mm=(10, 10, 120), wall_thickness_mm=(6, 0.8, 10))
    assert any("no channel" in r for r in get_subsystem("uchannel").check_invariants(led))


def test_panel_window_too_big(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "panel", window_width_mm=(95, 5, 250))
    assert any("frame" in r for r in get_subsystem("panel").check_invariants(led))


# --- real geometry ----------------------------------------------------------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
@pytest.mark.parametrize("name,tag", [("uchannel", "channel.body"), ("panel", "panel.body"), ("washer", "body.cyl")])
def test_geometry_builds(base_ledger, seeded, name, tag):
    part = get_subsystem(name).geometry_builder(seeded(base_ledger, name))
    assert part.solid is not None
    assert tag in part.tag_keys
