"""Saddle clamp / P-clamp — open semi-circular cradle + two base-flange mounting holes."""

from __future__ import annotations

import importlib.util

import pytest

# Explicit import (not routed through packages/subsystems/__init__.py's bottom import list, which
# doesn't wire this module in yet) — triggers this module's own register_subsystem() call so the
# registry is populated for this test process.
import packages.subsystems.saddle_clamp  # noqa: F401
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "saddle_clamp" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("saddle_clamp")
    assert sub.name == "saddle_clamp"
    assert sub.description == (
        "Open semi-circular saddle/P-clamp — cradles a cylindrical item "
        "(fan housing, pipe, tube) with two mounting bolts"
    )
    assert sub.applicable_disciplines == ("structures", "manufacturing", "thermal")
    assert sub.fea_eligible is False


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "saddle_clamp")
    vol = get_subsystem("saddle_clamp").volume_mm3(led)
    assert vol > 0.0


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "saddle_clamp")
    reasons = get_subsystem("saddle_clamp").check_invariants(led)
    assert reasons == [], f"saddle_clamp default seeds must satisfy invariants: {reasons}"


def test_invariant_violation_height_too_small(base_ledger, seeded_with):
    # height_mm far too small relative to bore_dia_mm — no floor left under the cradle.
    led = seeded_with(base_ledger, "saddle_clamp", height_mm=(15.0, 10.0, 100.0))
    reasons = get_subsystem("saddle_clamp").check_invariants(led)
    assert reasons != []
    assert any("floor" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    part = get_subsystem("saddle_clamp").geometry_builder(seeded(base_ledger, "saddle_clamp"))
    assert part.solid is not None
    assert part.solid.is_valid
    assert {"base.body", "cradle.channel", "mount[0].bore", "mount[1].bore"} <= part.tag_keys
    # OPEN channel, not a closed hole: the block minus the cradle cut and the two mounting holes
    # must still be a SINGLE connected manifold body.
    assert len(list(part.solid.solids())) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_mount_holes_clear_the_channel(base_ledger, seeded):
    # The mounting holes must sit in solid "ear" material beside the channel (|y| > bore radius),
    # not at y=0 under the open cradle where only a thin floor remains — a hole centered under the
    # channel wouldn't be a meaningful through-bolt feature.
    part = get_subsystem("saddle_clamp").geometry_builder(seeded(base_ledger, "saddle_clamp"))
    for tag in ("mount[0].bore", "mount[1].bore"):
        _, y = part.tags[tag]["center"]
        assert abs(y) > 35.0, f"{tag} at y={y} overlaps the 70mm cradle's radius (35mm)"
