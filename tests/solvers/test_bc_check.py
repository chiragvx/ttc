"""bc_check.py — the 2026-07-15 defense-in-depth fix for the confirmed BC-face-fragmentation bug:
a hole/pocket/slot that intersects (without severing) the validated cantilever methodology's clamp
(min-X) or load (max-X) face silently hands the solver a FRAGMENT of the true boundary face
(packages/truth_plane/solvers/mesh.py::_axis_extreme_surface picks exactly ONE face by bounding-box
centre) — an under-constrained/under-loaded model producing a confident, wrong FS with no error.

Pure build123d, no gmsh — runs on any box with build123d installed."""

from __future__ import annotations

import importlib.util

import pytest

HAS_B123D = importlib.util.find_spec("build123d") is not None
pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")


def _plate():
    import build123d as bd
    return bd.Box(100, 40, 5).solid()  # X=100 long (clamp/load axis), Y=40 wide, Z=5 thick


def test_uncut_plate_is_intact():
    from packages.truth_plane.solvers.bc_check import bc_faces_intact
    plate = _plate()
    assert bc_faces_intact(plate, plate) is True


def test_a_hole_through_the_middle_does_not_touch_either_end_face():
    import build123d as bd
    from packages.truth_plane.solvers.bc_check import bc_faces_intact

    plate = _plate()
    hole = (bd.Pos(0, 0, 0) * bd.Cylinder(8, 10)).solid()
    cut = plate - hole
    assert len(cut.solids()) == 1
    assert bc_faces_intact(plate, cut) is True


def test_a_hole_through_the_clamp_face_is_caught():
    """The confirmed bug: a hole positioned near the min-X (clamp) end punches through that face,
    splitting it into fragments that still sum to LESS than the original — bc_faces_intact must
    catch this instead of silently letting a fragment stand in for the whole face."""
    import build123d as bd
    from packages.truth_plane.solvers.bc_check import bc_faces_intact

    plate = _plate()
    # centered at x=-50 (the min-X edge), radius 8 -> spans x=[-58,-42], well past the x=-50 boundary
    hole = (bd.Pos(-50, 0, 0) * bd.Cylinder(8, 10)).solid()
    cut = plate - hole
    assert len(cut.solids()) == 1  # doesn't sever -- the existing check alone would let this through
    assert bc_faces_intact(plate, cut) is False


def test_a_hole_through_the_load_face_is_caught():
    import build123d as bd
    from packages.truth_plane.solvers.bc_check import bc_faces_intact

    plate = _plate()
    hole = (bd.Pos(50, 0, 0) * bd.Cylinder(8, 10)).solid()  # max-X (load) end this time
    cut = plate - hole
    assert len(cut.solids()) == 1
    assert bc_faces_intact(plate, cut) is False


def test_a_small_nick_within_tolerance_is_not_flagged():
    """A cut that barely grazes the boundary face (well under the 1% area tolerance) must not
    false-positive -- the check is meant to catch a REAL compromise of the boundary, not tessellation
    noise or a negligible nick."""
    import build123d as bd
    from packages.truth_plane.solvers.bc_check import bc_faces_intact

    plate = _plate()  # min-X face area = 40 * 5 = 200 mm^2
    # a tiny cylinder barely clipping the very corner of the min-X face (a small fraction of 200mm^2)
    tiny = (bd.Pos(-50, 19, 2) * bd.Cylinder(0.5, 2)).solid()
    cut = plate - tiny
    assert len(cut.solids()) == 1
    assert bc_faces_intact(plate, cut) is True
