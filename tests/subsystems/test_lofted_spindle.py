"""Lofted spindle — general body-of-revolution primitive (loft + hollow shell)."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "lofted_spindle" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("lofted_spindle")
    assert sub.name == "lofted_spindle"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "lofted_spindle")
    v = get_subsystem("lofted_spindle").volume_mm3(led)
    assert v > 0.0


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "lofted_spindle")
    reasons = get_subsystem("lofted_spindle").check_invariants(led)
    assert reasons == [], f"lofted_spindle default seeds must satisfy invariants: {reasons}"


def test_defaults_are_circular(base_ledger, seeded):
    # max_height_mm == max_width_mm by default — the elliptical option must not silently change the
    # original circular behavior for anyone who doesn't touch it.
    led = seeded(base_ledger, "lofted_spindle")
    inst = led.instances[led.root_id]
    assert inst.params["max_width_mm"].value == inst.params["max_height_mm"].value


def test_tapers_overlap_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_spindle",
                     start_taper_mm=(100.0, 0.0, 500.0), end_taper_mm=(100.0, 0.0, 500.0))
    reasons = get_subsystem("lofted_spindle").check_invariants(led)
    assert any("tapers overlap" in r for r in reasons)


def test_tip_width_not_narrower_than_max_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_spindle", start_width_mm=(45.0, 0.0, 300.0))
    reasons = get_subsystem("lofted_spindle").check_invariants(led)
    assert any("start_width" in r and "max_width" in r for r in reasons)


def test_tip_height_not_narrower_than_max_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_spindle", start_height_mm=(45.0, 0.0, 300.0))
    reasons = get_subsystem("lofted_spindle").check_invariants(led)
    assert any("start_height" in r and "max_height" in r for r in reasons)


def test_wall_thickness_violates_min_wall_at_tip(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_spindle", wall_thickness_mm=(10.0, 0.8, 15.0))
    reasons = get_subsystem("lofted_spindle").check_invariants(led)
    assert any("min wall" in r or "need >=" in r for r in reasons)


def test_flattened_config_registers_and_positive_volume(base_ledger, seeded_with):
    # width != height at every plateau/tip — the new elliptical option, not the circular default.
    led = seeded_with(base_ledger, "lofted_spindle",
                     max_width_mm=(60.0, 10.0, 300.0), max_height_mm=(30.0, 10.0, 300.0),
                     start_width_mm=(30.0, 0.0, 300.0), start_height_mm=(15.0, 0.0, 300.0),
                     end_width_mm=(30.0, 0.0, 300.0), end_height_mm=(15.0, 0.0, 300.0))
    v = get_subsystem("lofted_spindle").volume_mm3(led)
    assert v > 0.0
    reasons = get_subsystem("lofted_spindle").check_invariants(led)
    assert reasons == [], f"flattened config must satisfy invariants: {reasons}"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "lofted_spindle")
    part = get_subsystem("lofted_spindle").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert "spindle.body" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_fully_pointed_both_ends(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_spindle",
                     start_width_mm=(0.0, 0.0, 300.0), start_height_mm=(0.0, 0.0, 300.0),
                     end_width_mm=(0.0, 0.0, 300.0), end_height_mm=(0.0, 0.0, 300.0))
    part = get_subsystem("lofted_spindle").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_blunt_both_ends(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_spindle",
                     start_width_mm=(15.0, 0.0, 300.0), start_height_mm=(15.0, 0.0, 300.0),
                     end_width_mm=(15.0, 0.0, 300.0), end_height_mm=(15.0, 0.0, 300.0))
    part = get_subsystem("lofted_spindle").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_flattened_ellipse(base_ledger, seeded_with):
    # max_width_mm != max_height_mm must build a REAL, noticeably non-circular cross-section — not
    # silently stay circular.
    led = seeded_with(base_ledger, "lofted_spindle",
                     max_width_mm=(80.0, 10.0, 300.0), max_height_mm=(30.0, 10.0, 300.0),
                     start_width_mm=(40.0, 0.0, 300.0), start_height_mm=(15.0, 0.0, 300.0),
                     end_width_mm=(40.0, 0.0, 300.0), end_height_mm=(15.0, 0.0, 300.0))
    part = get_subsystem("lofted_spindle").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    bb = part.solid.bounding_box()
    y_size = bb.max.Y - bb.min.Y
    z_size = bb.max.Z - bb.min.Z
    assert y_size > 0.0 and z_size > 0.0
    # Y (width) and Z (height) bounding-box extents must differ noticeably — a real ellipse, not a
    # circle that happened to keep the old proportions.
    assert abs(y_size - z_size) / max(y_size, z_size) > 0.2, (
        f"expected a noticeably non-square cross-section, got Y={y_size:.1f} Z={z_size:.1f}"
    )


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    # Defaults are a gentle taper (start/end = half of max), NOT the fully-pointed extreme —
    # see lofted_spindle.py's module/_volume docstrings: the smooth-loft-vs-closed-form delta grows
    # far past "a few percent" as tip dimensions approach 0, since the hollowing loft's cavity
    # necessarily caps itself short of a true point. This test covers the well-behaved default case.
    led = seeded(base_ledger, "lofted_spindle")
    approx = get_subsystem("lofted_spindle").volume_mm3(led)
    part = get_subsystem("lofted_spindle").geometry_builder(led)
    real = part.solid.volume
    rel_err = abs(approx - real) / real
    assert rel_err < 0.15, f"approx {approx:.1f} vs real build {real:.1f} volume (err {rel_err:.1%})"
