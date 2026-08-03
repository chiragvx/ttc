"""Knurled Nut — small cylindrical thumb nut (no knurl grooves), structural envelope only."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model, resolve_namespace
from packages.subsystems.knurled_nut import _volume

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "knurled_nut" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("knurled_nut")
    assert sub.name == "knurled_nut"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "knurled_nut")
    v = get_subsystem("knurled_nut").volume_mm3(led)
    assert v > 0.0


def test_volume_matches_hand_computed_value(base_ledger, seeded_with):
    # dia_mm=12.0 -> radius 6.0mm, height_mm=8.0mm: V = pi * r^2 * h = pi * 36 * 8
    led = seeded_with(base_ledger, "knurled_nut", dia_mm=(12.0, 4.0, 30), height_mm=(8.0, 2.0, 20))
    expected = math.pi * 6.0 ** 2 * 8.0
    vol = get_subsystem("knurled_nut").volume_mm3(led)
    assert vol == pytest.approx(expected)

    # Cross-check directly against the subsystem module's own _volume(), not just the registry wiring.
    ns = resolve_namespace(get_subsystem_model("knurled_nut"), led)
    assert _volume(ns) == pytest.approx(expected)


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "knurled_nut")
    reasons = get_subsystem("knurled_nut").check_invariants(led)
    assert reasons == [], f"knurled_nut default seeds must satisfy invariants: {reasons}"


def test_too_short_violates_min_wall(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "knurled_nut", height_mm=(0.5, 0.1, 50))
    reasons = get_subsystem("knurled_nut").check_invariants(led)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_interfaces_declared_as_cylinder_ends():
    assert [i.name for i in get_subsystem_model("knurled_nut").interfaces] == ["bottom", "top"]


def test_interfaces_land_at_expected_coordinates(base_ledger, seeded_with):
    # height_mm=8.0 -> cylinder_end_interfaces("height_mm") halves it: bottom/top sit +/-4.0mm along
    # local Z, each normal pointing outward from the part (bottom: -Z, top: +Z).
    led = seeded_with(base_ledger, "knurled_nut", height_mm=(8.0, 2.0, 20))
    model = get_subsystem_model("knurled_nut")
    ns = resolve_namespace(model, led)
    frames = {i.name: i.frame(ns) for i in model.interfaces}
    assert frames["bottom"].origin == pytest.approx((0.0, 0.0, -4.0))
    assert frames["bottom"].normal == pytest.approx((0.0, 0.0, -1.0))
    assert frames["top"].origin == pytest.approx((0.0, 0.0, 4.0))
    assert frames["top"].normal == pytest.approx((0.0, 0.0, 1.0))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "knurled_nut")
    part = get_subsystem("knurled_nut").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys
