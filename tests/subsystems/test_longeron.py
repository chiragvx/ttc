"""Longeron — a long straight structural rail (fuselage/wing spanwise member)."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "longeron" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("longeron")
    assert sub.name == "longeron"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "longeron")
    v = get_subsystem("longeron").volume_mm3(led)
    assert v > 0.0


def test_volume_matches_box(base_ledger, seeded):
    led = seeded(base_ledger, "longeron")
    v = get_subsystem("longeron").volume_mm3(led)
    assert v == pytest.approx(400.0 * 20.0 * 10.0)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "longeron")
    reasons = get_subsystem("longeron").check_invariants(led)
    assert reasons == [], f"longeron default seeds must satisfy invariants: {reasons}"


def test_too_thin_violates_min_wall(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "longeron", height_mm=(0.5, 0.1, 50))
    reasons = get_subsystem("longeron").check_invariants(led)
    assert any("min wall" in r for r in reasons)


def test_too_thin_width_also_violates_min_wall(base_ledger, seeded_with):
    """2026-07-16 regression guard: `_check` used to validate height_mm only, missing a too-thin
    width_mm entirely even though width×height is a single rectangular cross-section where either
    dimension can be the thin one."""
    led = seeded_with(base_ledger, "longeron", width_mm=(0.5, 0.1, 100))
    reasons = get_subsystem("longeron").check_invariants(led)
    assert any("min wall" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "longeron")
    part = get_subsystem("longeron").geometry_builder(led)
    assert part.solid is not None
    assert "longeron.body" in part.tag_keys
