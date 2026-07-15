"""Geometric defense-in-depth for the validated cantilever FS methodology's boundary-condition
faces (`packages/truth_plane/solvers/mesh.py::_axis_extreme_surface` picks exactly ONE face by its
bounding-box centre being most extreme along an axis -- the min-X "clamp" face and the max-X "load"
face for every cantilever case this pipeline solves). A hole/pocket/slot that intersects one of those
faces WITHOUT severing the part into multiple solids still passes the existing single-solid check,
but silently hands the solver a FRAGMENT of the true boundary face -- the clamp/load only constrains
part of the real cross-section, producing a confident, wrong FS with no error at all (2026-07-15
audit finding, confirmed live: a hole punched through a plate's clamp end splits that single face
into two ~60mm^2 fragments whose SUM is still only 120mm^2 of the original 200mm^2 -- `_axis_extreme_
surface` would silently pick just one of the two, missing 140mm^2 of the true boundary).

Pure build123d (no gmsh/CalculiX), so this runs identically to the geometry pipeline everything else
in this repo already builds against, and is unit-testable without the Linux-only solver toolchain.
"""

from __future__ import annotations

# The SAME two selectors packages/truth_plane/solvers/fs.py::DEFAULT_FACES uses for every
# fea_eligible subsystem today (clamp min-X / load max-X cantilever convention).
_FACE_SELECTORS = ((0, False), (0, True))  # (axis, want_max)
_AREA_TOL = 0.01  # 1% -- generous enough to absorb tessellation/re-triangulation noise, tight
                  # enough to catch a real material loss at the boundary face
_COORD_EPS_MM = 1e-3


def _coord(bbox, axis: int, want_max: bool) -> float:
    return (bbox.max.X if want_max else bbox.min.X,
           bbox.max.Y if want_max else bbox.min.Y,
           bbox.max.Z if want_max else bbox.min.Z)[axis]


def _extent(bbox, axis: int) -> tuple[float, float]:
    if axis == 0:
        return (bbox.min.X, bbox.max.X)
    if axis == 1:
        return (bbox.min.Y, bbox.max.Y)
    return (bbox.min.Z, bbox.max.Z)


def _extreme_face_area(solid, axis: int, want_max: bool) -> float:
    """Total area of every face whose bounding box is genuinely PLANAR AND PERPENDICULAR to `axis`
    (collapsed to a single coordinate along it -- a real end cap, not a side face that merely happens
    to reach that far along one edge) AND sits at `solid`'s OWN extreme coordinate along `axis` --
    matches (in build123d, not gmsh) the same axis-extreme selection
    `solvers/mesh.py::_axis_extreme_surface` uses, so this check and the real FEA boundary-condition
    selection agree on what counts as "the" extreme face. A box's own long side faces span the FULL
    length (their bounding box touches BOTH extremes at once) -- the planarity check is what excludes
    those; without it, every side face would be wrongly counted as part of BOTH end caps. Summing
    every coplanar fragment of the real end cap (rather than picking just one, the way the actual
    mesh face-selector does) is what makes the before/after area comparison in `bc_faces_intact`
    correct regardless of how many pieces a cut split the original face into."""
    extreme = _coord(solid.bounding_box(), axis, want_max)
    total = 0.0
    for face in solid.faces():
        lo, hi = _extent(face.bounding_box(), axis)
        if abs(hi - lo) > _COORD_EPS_MM:
            continue  # not planar/perpendicular to this axis -- a side face, not an end cap
        if abs(lo - extreme) <= _COORD_EPS_MM:
            total += face.area
    return total


def bc_faces_intact(uncut_solid, cut_solid) -> bool:
    """True iff neither the clamp (min-X) nor the load (max-X) boundary face lost more than
    `_AREA_TOL` of its area between the un-cut and cut geometry. False means a cut feature
    compromised one of the faces the FEA boundary conditions are geometrically pinned to -- the
    caller must treat this exactly like the existing severed-island case: an honest "unknown", never
    a fabricated FS on a boundary condition that no longer represents the real part."""
    for axis, want_max in _FACE_SELECTORS:
        before = _extreme_face_area(uncut_solid, axis, want_max)
        if before <= 0:
            continue  # nothing to compare against -- don't false-flag on a degenerate uncut face
        after = _extreme_face_area(cut_solid, axis, want_max)
        if after < before * (1.0 - _AREA_TOL):
            return False
    return True
