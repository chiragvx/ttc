"""Lofted hull — asymmetric top/bottom body of revolution + localized canopy bump."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "lofted_hull" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("lofted_hull")
    assert sub.name == "lofted_hull"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "lofted_hull")
    v = get_subsystem("lofted_hull").volume_mm3(led)
    assert v > 0.0


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "lofted_hull")
    reasons = get_subsystem("lofted_hull").check_invariants(led)
    assert reasons == [], f"lofted_hull default seeds must satisfy invariants: {reasons}"


def test_tapers_overlap_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_hull",
                     start_taper_mm=(250.0, 0.0, 1000.0), end_taper_mm=(250.0, 0.0, 1000.0))
    reasons = get_subsystem("lofted_hull").check_invariants(led)
    assert any("tapers overlap" in r for r in reasons)


def test_start_width_not_narrower_than_max_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_hull", start_width_mm=(90.0, 0.0, 500.0))
    reasons = get_subsystem("lofted_hull").check_invariants(led)
    assert any("start_width" in r and "max_width" in r for r in reasons)


def test_end_width_not_narrower_than_max_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_hull", end_width_mm=(90.0, 0.0, 500.0))
    reasons = get_subsystem("lofted_hull").check_invariants(led)
    assert any("end_width" in r and "max_width" in r for r in reasons)


def test_wall_thickness_violates_min_wall_at_tip(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_hull", wall_thickness_mm=(12.0, 0.8, 15.0))
    reasons = get_subsystem("lofted_hull").check_invariants(led)
    assert any("min wall" in r or "need >=" in r for r in reasons)


def test_bump_zone_overflow_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_hull",
                     bump_start_pct=(70.0, 0.0, 100.0), bump_length_pct=(50.0, 0.0, 100.0))
    reasons = get_subsystem("lofted_hull").check_invariants(led)
    assert any("bump_start_pct" in r and "bump_length_pct" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "lofted_hull")
    part = get_subsystem("lofted_hull").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert "hull.body" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_pronounced_bump(base_ledger, seeded_with):
    # bump_height_mm=25 is a REAL, pronounced canopy (more than doubling the base top height-half of
    # 22.5mm) but stays within the empirically-validated-safe zone — see lofted_hull.py's module
    # docstring and _build()'s fallback: a bump this size at these proportions was verified directly
    # (this session) to loft/hollow correctly, unlike a much larger bump at the same proportions
    # (test_extreme_bump_falls_back_to_solid_safely below). is_valid ALONE is not proof of correct
    # volume (see the module docstring's confirmed finding), so this test also checks volume.
    led = seeded_with(base_ledger, "lofted_hull",
                     max_height_top_mm=(45.0, 5.0, 300.0), max_height_bottom_mm=(35.0, 5.0, 300.0),
                     bump_start_pct=(35.0, 0.0, 100.0), bump_length_pct=(30.0, 0.0, 100.0),
                     bump_height_mm=(25.0, 0.0, 150.0))
    sub = get_subsystem("lofted_hull")
    part = sub.geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1
    assert part.tags["hull.body"]["hollowed"] is True
    approx = sub.volume_mm3(led)
    real = part.solid.volume
    rel_err = abs(approx - real) / real
    assert rel_err < 0.15, f"approx {approx:.1f} vs real build {real:.1f} volume (err {rel_err:.1%})"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_pointed_both_ends(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "lofted_hull",
                     start_width_mm=(0.0, 0.0, 500.0), end_width_mm=(0.0, 0.0, 500.0))
    part = get_subsystem("lofted_hull").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "lofted_hull")
    approx = get_subsystem("lofted_hull").volume_mm3(led)
    part = get_subsystem("lofted_hull").geometry_builder(led)
    real = part.solid.volume
    rel_err = abs(approx - real) / real
    assert rel_err < 0.15, f"approx {approx:.1f} vs real build {real:.1f} volume (err {rel_err:.1%})"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_no_silent_twist_along_length(base_ledger, seeded_with):
    """THE critical test motivating this subsystem's silent-twist risk finding (see lofted_hull.py's
    module docstring): is_valid=True alone is explicitly NOT sufficient evidence of a correct loft —
    a rotated interior station produces a smooth, silent corkscrew that still reports is_valid=True.
    Slice the built solid's OUTER wall at several stations along its length and find each slice's
    "topmost point" (a real asymmetry landmark — by construction, _hull_profile_points always puts
    the profile's absolute top at y=0 relative to the profile's own local frame, at every station,
    with no per-station rotation). If a per-station rotation bug were introduced, this landmark would
    drift/spiral in Y as x increases; this test fails loudly if it does, rather than just checking
    is_valid."""
    import build123d as bd

    # bump_height_mm=25 — a pronounced, but empirically-validated-safe, canopy (see
    # test_geometry_builds_pronounced_bump and lofted_hull.py's module docstring); this test is about
    # the twist/orientation landmark on the OUTER wall, which is what a hollowed, genuinely-bumped
    # build exercises (an extreme bump_height_mm would trip _build()'s solid-fallback safety net
    # instead — see test_extreme_bump_falls_back_to_solid_safely — which is a real, valid part but
    # not what THIS test means to probe).
    led = seeded_with(base_ledger, "lofted_hull",
                     max_height_top_mm=(45.0, 5.0, 300.0), max_height_bottom_mm=(35.0, 5.0, 300.0),
                     bump_start_pct=(35.0, 0.0, 100.0), bump_length_pct=(30.0, 0.0, 100.0),
                     bump_height_mm=(25.0, 0.0, 150.0))
    part = get_subsystem("lofted_hull").geometry_builder(led)
    solid = part.solid
    assert solid.is_valid
    assert part.tags["hull.body"]["hollowed"] is True

    bb = solid.bounding_box()
    length = bb.max.X - bb.min.X
    query_xs = [length * f for f in (0.08, 0.2, 0.35, 0.5, 0.6, 0.75, 0.9, 0.98)]

    landmarks = []
    for xq in query_xs:
        plane = bd.Plane(origin=(xq, 0, 0), z_dir=(1, 0, 0))
        face = solid.intersect(plane)
        assert face is not None, f"no cross-section at x={xq:.1f}"
        outer_wire = face.outer_wire()
        best = None
        n_samples = 200
        for edge in outer_wire.edges():
            for i in range(n_samples):
                pos = edge.position_at(i / n_samples)
                if best is None or pos.Z > best.Z:
                    best = pos
        assert best is not None
        landmarks.append((xq, best.Y, best.Z))

    # The topmost point must stay near Y=0 (the profile's own top-center, by construction) at EVERY
    # station — a real per-station rotation would push this progressively off-center as x increases.
    max_drift = max(abs(y) for _x, y, _z in landmarks)
    assert max_drift < 5.0, (
        f"topmost-point Y drifted up to {max_drift:.2f} mm along the length — possible silent twist: "
        f"{landmarks}"
    )

    # And the landmark's angular position (atan2(z, y), measured from the profile's own center)
    # should stay clustered near +90 degrees (straight up) at every station, not sweep through a
    # range consistent with a spiral.
    angles_deg = [math.degrees(math.atan2(z, y)) for _x, y, z in landmarks]
    for a in angles_deg:
        assert abs(a - 90.0) < 15.0, f"landmark angles drifted from vertical: {angles_deg}"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_extreme_bump_falls_back_to_solid_safely(base_ledger, seeded_with):
    """CONFIRMED THIS SESSION (see lofted_hull.py's module docstring and _build()): a sufficiently
    pronounced canopy bump — a LOCALIZED excursion surrounded by much flatter stations — can make
    bd.loft()'s cavity surface come out self-intersecting/mis-oriented, silently subtracting far LESS
    material than intended (still is_valid=True; measured ~4x the intended shell volume in one
    reproduction at bump_height_mm=40 with these exact proportions). No parameter tuning (station
    density up to 188, ruled=True) fixed the ROOT loft defect, and the failure threshold is an
    absolute-scale-dependent OCCT numerical-tolerance interaction, not a clean formula safe to
    invariant-gate. _build()'s safety net instead detects the resulting gross volume mismatch and
    falls back to the (verified-correct-volume in every reproduction) unhollowed outer loft — this
    test locks that fallback in as a regression guard: it must keep firing for this exact
    known-bad config, producing a VALID, correctly-volumed (matching the outer loft, not a
    corrupted subtraction) — if unintentionally hollow — part, rather than silently shipping the
    ~4x-too-large defect."""
    led = seeded_with(base_ledger, "lofted_hull",
                     max_height_top_mm=(45.0, 5.0, 300.0), max_height_bottom_mm=(35.0, 5.0, 300.0),
                     bump_start_pct=(35.0, 0.0, 100.0), bump_length_pct=(30.0, 0.0, 100.0),
                     bump_height_mm=(40.0, 0.0, 150.0))
    sub = get_subsystem("lofted_hull")
    part = sub.geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1
    # The safety net must have tripped: this exact config is confirmed to corrupt the cavity subtract.
    assert part.tags["hull.body"]["hollowed"] is False
    # And the resulting (unhollowed) solid's volume must be sane — nowhere near the corrupted ~4x
    # blowup a broken subtraction produced in the original repro.
    approx_shell = sub.volume_mm3(led)
    assert part.solid.volume > approx_shell * 2.0, (
        "expected the solid-fallback volume (~the full outer loft) to be well above the intended "
        "hollow-shell approximation — if this shrinks back down, double-check the fallback still "
        "triggers for this known-bad config rather than a re-corrupted hollow result"
    )
