"""Enclosure subsystem — new-style (Phase C). Covers registration, invariants, volume, prompt filter, geometry."""

from __future__ import annotations

import importlib.util

import pytest

from packages.agents.prompt_builder import build_system_prompt
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem


def test_enclosure_registered():
    assert "enclosure" in SUBSYSTEM_REGISTRY
    assert get_subsystem("enclosure").applicable_disciplines == ("structures", "manufacturing", "thermal")


# --- invariants -------------------------------------------------------------

def test_invariants_ok_by_default(base_ledger, seeded):
    assert get_subsystem("enclosure").check_invariants(seeded(base_ledger, "enclosure")) == []


def test_invariant_flags_sub_min_wall(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "enclosure", wall_thickness_mm=(0.5, 0.1, 6.0))
    reasons = get_subsystem("enclosure").check_invariants(led)
    assert any("min wall" in r for r in reasons)


def test_invariant_flags_no_cavity(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "enclosure",
                     box_width_mm=(40, 40, 200), box_depth_mm=(30, 30, 200),
                     wall_thickness_mm=(20, 0.8, 30))
    reasons = get_subsystem("enclosure").check_invariants(led)
    assert any("no cavity" in r for r in reasons)


# --- volume (drives mass / print-time telemetry) ----------------------------

def test_combined_volume_box_plus_lid(base_ledger, seeded):
    """Volume is now the sum of box shell + lid plate + lid lip (one design → two printed parts)."""
    led = seeded(base_ledger, "enclosure")
    vol = get_subsystem("enclosure").volume_mm3(led)
    # box shell = 80·60·40 − 76·56·38 = 30272
    # lid plate = 80·60·2 = 9600
    # lid lip (outer 75.6·55.6 − inner 71.6·51.6) · 5 = 508.80 · 5 = 2544
    assert vol == pytest.approx(30272.0 + 9600.0 + 2544.0)


# --- subsystem-scoped prompt filter -----------------------------------------

def test_enclosure_prompt_shows_box_not_plate(base_ledger, seeded):
    prompt = build_system_prompt(get_subsystem("enclosure"), seeded(base_ledger, "enclosure"))
    assert "Subsystem: Enclosure" in prompt
    assert "instances.root.params.box_width_mm" in prompt
    assert "instances.root.params.plate_width_mm" not in prompt  # bracket dims hidden for an enclosure


def test_bracket_prompt_shows_plate_not_box(base_ledger):
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "instances.root.params.plate_width_mm" in prompt
    assert "instances.root.params.box_width_mm" not in prompt


# --- real geometry ----------------------------------------------------------

@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="needs build123d")
def test_enclosure_geometry_builder(base_ledger, seeded):
    """The merged enclosure produces box shell + lid as one compound (two printed parts)."""
    part = get_subsystem("enclosure").geometry_builder(seeded(base_ledger, "enclosure"))
    assert part.solid is not None
    # box tags
    assert {"shell.body", "cavity.void"} <= part.tag_keys
    # lid tags (this is what the merge added)
    assert {"lid.plate", "lid.lip"} <= part.tag_keys
