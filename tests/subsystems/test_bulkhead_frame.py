"""Bulkhead frame — ring frame perpendicular to the fuselage axis + bolt-hole pattern."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "bulkhead_frame" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("bulkhead_frame")
    assert sub.name == "bulkhead_frame"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "bulkhead_frame")
    v = get_subsystem("bulkhead_frame").volume_mm3(led)
    assert v > 0.0


def test_volume_matches_ring_minus_bolts(base_ledger, seeded):
    led = seeded(base_ledger, "bulkhead_frame")
    v = get_subsystem("bulkhead_frame").volume_mm3(led)
    ring = math.pi * (50.0**2 - 40.0**2) * 3.0
    bolts = 6 * math.pi * (2.0**2) * 3.0
    assert v == pytest.approx(ring - bolts)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "bulkhead_frame")
    reasons = get_subsystem("bulkhead_frame").check_invariants(led)
    assert reasons == [], f"bulkhead_frame default seeds must satisfy invariants: {reasons}"


def test_flange_too_wide_collapses_inner_diameter(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "bulkhead_frame",
                     outer_dia_mm=(40, 40, 400), flange_width_mm=(30, 3, 40))
    reasons = get_subsystem("bulkhead_frame").check_invariants(led)
    assert any("inner diameter" in r for r in reasons)


def test_bolt_hole_too_big_violates_edge_distance(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "bulkhead_frame", bolt_hole_dia_mm=(8, 2, 8))
    reasons = get_subsystem("bulkhead_frame").check_invariants(led)
    assert any("edge distance" in r for r in reasons)


def test_bolt_holes_overlap_on_crowded_circle(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "bulkhead_frame",
                     flange_width_mm=(30, 3, 40), bolt_hole_dia_mm=(14, 2, 15),
                     num_bolt_holes=(16, 3, 16))
    reasons = get_subsystem("bulkhead_frame").check_invariants(led)
    assert any("overlap" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "bulkhead_frame")
    part = get_subsystem("bulkhead_frame").geometry_builder(led)
    assert part.solid is not None
    assert "frame.body" in part.tag_keys
