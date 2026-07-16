"""NACA wing — full-span lofted wing panel, real NACA 4-digit symmetric airfoil cross-section."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem
from packages.subsystems._naca_airfoil import naca4_half_thickness, naca4_profile_points

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered():
    assert "naca_wing" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("naca_wing")
    assert sub.name == "naca_wing"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_closed_trailing_edge_exact():
    """The whole point of the -0.1036 coefficient choice (see _naca_airfoil.py's module docstring):
    yt must be EXACTLY 0.0 at the trailing edge, not merely small."""
    assert naca4_half_thickness(100.0, chord=100.0, thickness_pct=12.0) == 0.0
    assert naca4_half_thickness(0.0, chord=100.0, thickness_pct=12.0) == 0.0


def test_naca0012_max_thickness_is_about_12_percent_of_chord():
    # NACA0012's defining property: max thickness ~= 12% of chord, roughly around 30% chord.
    chord = 200.0
    max_yt = max(naca4_half_thickness(x, chord, 12.0) for x in [chord * f / 100.0 for f in range(0, 101)])
    max_thickness = 2.0 * max_yt
    assert max_thickness == pytest.approx(chord * 0.12, rel=0.02)


def test_profile_points_closed_loop_shares_no_duplicate_coordinate():
    pts = naca4_profile_points(0.0, chord=100.0, thickness_pct=12.0, n_per_side=20)
    assert len(pts) == 2 * 20 - 2
    # first (leading edge) and last (near leading edge, closes back via periodic spline) are distinct
    assert pts[0] != pts[-1]
    # no other duplicate coordinates anywhere in the loop
    assert len(set(pts)) == len(pts)


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "naca_wing")
    v = get_subsystem("naca_wing").volume_mm3(led)
    assert v > 0.0


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "naca_wing")
    reasons = get_subsystem("naca_wing").check_invariants(led)
    assert reasons == [], f"naca_wing default seeds must satisfy invariants: {reasons}"


def test_thin_tip_violates_min_wall(base_ledger, seeded_with):
    # a 10mm tip chord at 6% thickness gives 0.6mm max thickness -- below the 0.8mm FDM floor.
    led = seeded_with(base_ledger, "naca_wing",
                     tip_chord_mm=(10.0, 10.0, 600.0), thickness_pct=(6.0, 6.0, 21.0))
    reasons = get_subsystem("naca_wing").check_invariants(led)
    assert any("max thickness" in r for r in reasons)


def test_reversed_taper_root_narrower_than_tip_is_rejected(base_ledger, seeded_with):
    """A wing narrower at the root than the tips (a backward "paddle" planform) is structurally
    invalid -- the root carries the highest bending load. Wing area/aspect-ratio/MAC are all
    algebraically blind to this (integrals over a symmetric chord ramp don't care which end holds the
    larger value), so this needs its own explicit check, not a tolerance on an existing one."""
    led = seeded_with(base_ledger, "naca_wing",
                     root_chord_mm=(20.0, 20.0, 600.0), tip_chord_mm=(600.0, 10.0, 600.0))
    reasons = get_subsystem("naca_wing").check_invariants(led)
    assert any("taper root-to-tip" in r for r in reasons), (
        f"expected a reversed-taper violation, got: {reasons}"
    )


def test_equal_root_and_tip_chord_is_not_a_reversed_taper(base_ledger, seeded_with):
    # the declared "straight (untapered) wing" case (root_chord_mm == tip_chord_mm) must NOT trip the
    # reversed-taper check -- only root < tip is invalid.
    led = seeded_with(base_ledger, "naca_wing", tip_chord_mm=(120.0, 10.0, 600.0))  # == root_chord_mm
    reasons = get_subsystem("naca_wing").check_invariants(led)
    assert not any("taper root-to-tip" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "naca_wing")
    part = get_subsystem("naca_wing").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1
    assert "wing.panel" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "naca_wing")
    sub = get_subsystem("naca_wing")
    approx = sub.volume_mm3(led)
    part = sub.geometry_builder(led)
    real = part.solid.volume
    rel_err = abs(approx - real) / real
    assert rel_err < 0.15, f"approx {approx:.1f} vs real build {real:.1f} volume (err {rel_err:.1%})"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_tapered_swept_dihedral(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "naca_wing",
                     root_chord_mm=(150.0, 20.0, 600.0), tip_chord_mm=(50.0, 10.0, 600.0),
                     sweep_deg=(20.0, -30.0, 45.0), dihedral_deg=(5.0, -10.0, 20.0))
    part = get_subsystem("naca_wing").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_untapered_straight_wing(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "naca_wing", tip_chord_mm=(120.0, 10.0, 600.0))  # == root_chord_mm
    part = get_subsystem("naca_wing").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert len(part.solid.solids()) == 1


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_no_silent_twist_along_span(base_ledger, seeded_with):
    """THE critical test motivating _naca_airfoil.py's LOCAL AXIS CONVENTION warning: is_valid=True
    alone is not sufficient evidence of a correct loft (see lofted_hull.py's module docstring on the
    exact same risk for its own profile generator). The span/loft axis is X (this file's own module
    docstring / lofted_spindle's convention). Slice the built solid at several stations along X and
    find each slice's topmost (max-Z) point -- a real asymmetry landmark: the NACA profile's peak
    thickness always sits at the SAME fraction of the local chord, on the SAME (upper) surface, by
    construction, at every station, regardless of how much that station's chord has tapered (a
    self-similar profile, zero sweep/dihedral here). Normalizing the landmark's Y position by that
    same slice's OWN measured chord (its Y-extent) isolates the "did it rotate" question from the
    expected "the chord tapers along the span" effect. If a per-station rotation bug were introduced,
    this normalized ratio would drift/spiral instead of staying constant; this test fails loudly if
    it does, rather than trusting is_valid alone."""
    import build123d as bd

    led = seeded_with(base_ledger, "naca_wing",
                     root_chord_mm=(150.0, 20.0, 600.0), tip_chord_mm=(60.0, 10.0, 600.0))
    part = get_subsystem("naca_wing").geometry_builder(led)
    solid = part.solid
    assert solid.is_valid

    bb = solid.bounding_box()
    span_len = bb.max.X - bb.min.X
    query_xs = [bb.min.X + span_len * f for f in (0.08, 0.25, 0.5, 0.75, 0.92)]

    ratios = []
    for xq in query_xs:
        plane = bd.Plane(origin=(xq, 0, 0), z_dir=(1, 0, 0))
        face = solid.intersect(plane)
        assert face is not None, f"no cross-section at x={xq:.1f}"
        outer_wire = face.outer_wire()
        best = None
        y_min, y_max = None, None
        n_samples = 200
        for edge in outer_wire.edges():
            for i in range(n_samples):
                pos = edge.position_at(i / n_samples)
                if best is None or pos.Z > best.Z:
                    best = pos
                y_min = pos.Y if y_min is None else min(y_min, pos.Y)
                y_max = pos.Y if y_max is None else max(y_max, pos.Y)
        assert best is not None
        chord_measured = y_max - y_min
        assert chord_measured > 1.0, f"degenerate cross-section at x={xq:.1f}"
        local_center = (y_min + y_max) / 2.0
        ratios.append((best.Y - local_center) / chord_measured)
        # Twist would also risk flipping the thickness peak to the LOWER surface — never negative Z.
        assert best.Z > 0.0, f"expected an upper-surface (Z>0) thickness peak at x={xq:.1f}, got Z={best.Z:.3f}"

    spread = max(ratios) - min(ratios)
    assert spread < 0.08, (
        f"chord-normalized landmark position drifted by {spread:.3f} across the span -- possible "
        f"silent twist: {ratios}"
    )


def _best_fit_line_max_deviation(xs: list[float], ys: list[float]) -> float:
    """Least-squares best-fit line y = a*x + b through (xs, ys); returns the max |residual|."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    a = num / den
    b = mean_y - a * mean_x
    return max(abs(y - (a * x + b)) for x, y in zip(xs, ys))


def _leading_edge_y(solid, xq: float):
    """The outer-wire point at minimum local Y at span station `xq` -- the leading-edge landmark
    (see `_naca_airfoil.py`'s LOCAL AXIS CONVENTION: leading edge sits at the most-negative Y in the
    profile's own chordwise frame, before any sweep offset is added)."""
    import build123d as bd

    plane = bd.Plane(origin=(xq, 0, 0), z_dir=(1, 0, 0))
    face = solid.intersect(plane)
    assert face is not None, f"no cross-section at x={xq:.1f}"
    outer_wire = face.outer_wire()
    best = None
    n_samples = 400
    for edge in outer_wire.edges():
        for i in range(n_samples):
            pos = edge.position_at(i / n_samples)
            if best is None or pos.Y < best.Y:
                best = pos
    assert best is not None
    return best.Y


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_sharp_straight_taper_no_dome_at_root(base_ledger, seeded_with):
    """THE direct regression test for the confirmed bug this session fixed: the wing root/peak used
    to look smoothly domed/curved (a Bezier-like bulge) instead of a sharp, straight-line taper (real
    swept wings have straight leading/trailing edges meeting at a sharp point at the root) -- caused
    by `_chord_at()` reusing the cosine-ease `ease_at` helper (zero slope right at the centerline)
    plus a non-ruled (`ruled=False`) loft. Build a real config with real sweep AND a real taper, slice
    the solid at several span stations on ONE side of the centerline (10/30/50/70/90% of the
    half-span from center to tip), find the leading-edge landmark at each slice, and assert those
    landmark positions fit a PERFECTLY STRAIGHT LINE as a function of span position -- an actual
    least-squares best-fit-line residual check, not just "monotonic"."""
    led = seeded_with(base_ledger, "naca_wing",
                     span_mm=(800.0, 100.0, 3000.0), root_chord_mm=(150.0, 20.0, 600.0),
                     tip_chord_mm=(60.0, 10.0, 600.0), sweep_deg=(35.0, -30.0, 45.0))
    part = get_subsystem("naca_wing").geometry_builder(led)
    solid = part.solid
    assert solid.is_valid
    assert len(solid.solids()) == 1

    half_span = 800.0 / 2.0
    query_xs = [half_span * f for f in (0.10, 0.30, 0.50, 0.70, 0.90)]
    ys = [_leading_edge_y(solid, xq) for xq in query_xs]

    max_dev = _best_fit_line_max_deviation(query_xs, ys)
    assert max_dev < 0.01, (
        f"leading-edge landmark deviates {max_dev:.4f} mm from a straight-line best fit -- the root "
        f"is domed/curved, not a sharp straight taper: xs={query_xs}, ys={ys}"
    )


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_old_ease_at_schedule_would_have_failed_straight_line_check():
    """Extra confidence (not required to prove the fix, but removes any doubt this is a real
    regression test rather than a tautology any schedule would pass): reproduces the OLD, pre-fix
    ease_at-based chord schedule + `ruled=False` loft standalone here (does NOT touch the real,
    now-fixed `naca_wing.py`) and shows the exact same straight-line landmark check above would have
    failed loudly under the old behavior -- a visibly domed/curved root, not a sharp taper."""
    import math

    import build123d as bd

    from packages.subsystems._loft_profiles import ease_at, taper_stations
    from packages.subsystems._naca_airfoil import naca4_profile_points

    span_mm, root_chord_mm, tip_chord_mm, sweep_deg, thickness_pct = 800.0, 150.0, 60.0, 35.0, 12.0
    half_span = span_mm / 2.0

    def old_chord_at(dist: float) -> float:
        return ease_at(dist, 0.0, 0.0, half_span, root_chord_mm, root_chord_mm, tip_chord_mm)

    def old_section(x: float):
        dist = abs(x)
        chord = old_chord_at(dist)
        y_offset = dist * math.tan(math.radians(sweep_deg))
        pts = naca4_profile_points(x, chord, thickness_pct, 20, y_offset=y_offset, z_offset=0.0)
        edge = bd.Spline(*pts, periodic=True)
        return bd.Face(bd.Wire([edge]))

    stations = [x - half_span for x in taper_stations(span_mm, half_span, half_span, 8)]
    solid = bd.loft([old_section(x) for x in stations], ruled=False)
    assert solid.is_valid

    query_xs = [half_span * f for f in (0.10, 0.30, 0.50, 0.70, 0.90)]
    ys = [_leading_edge_y(solid, xq) for xq in query_xs]

    max_dev = _best_fit_line_max_deviation(query_xs, ys)
    assert max_dev > 1.0, (
        f"expected the OLD ease_at/ruled=False schedule to visibly fail a straight-line check "
        f"(a domed root), but max deviation was only {max_dev:.4f} mm"
    )
