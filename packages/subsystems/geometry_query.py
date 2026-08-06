"""Geometry-query utilities (2026-08-05) -- Phase 0 of the gearbox-housing-generation initiative
(`C:\\Users\\Chirag\\.claude\\plans\\spicy-exploring-cupcake.md`). Everything downstream (Phase 1's
compact kinematic placement, Phase 2's `compute_envelope` deriving a housing from where the gears/
shafts actually ended up) needs a correct, SHARED way to ask "where does instance X's REAL, BUILT,
WORLD-placed geometry actually sit" -- today that build -> rotate -> translate sequence was
independently duplicated, per-instance, in THREE places (`assembly.py::_y_extent_mm`,
`validate.py::_placed`, `blueprint.py::_placed_triangles`), never unioned across a group. This module
is that shared utility, plus the one genuinely NEW op none of the three needed before: a real solid
convex hull over a GROUP of instances.

Design decisions worth knowing before touching this file:

- **`BBox` lives HERE, not in `validate.py`** (where it originated). `validate.py` needs to call INTO
  this module (`world_bbox` replaces its `_placed`'s per-instance block), so if `BBox` stayed defined
  in `validate.py` and this module imported it from there, `validate.py` -> `geometry_query.py` ->
  `validate.py` would be a straight import cycle. This module has no reason to depend on `validate.py`
  at all, so the type alias moves to the lower module in the dependency graph (here) and `validate.py`
  imports it back (`from packages.subsystems.geometry_query import BBox`) -- zero change to
  `validate.py`'s own public shape, every existing `BBox`-typed signature there is unaffected.

- **`raw_build` is the one function here that CAN raise** -- everything else commits to "never raises,
  log + return None on any failure" (matching `assembly.py::_y_extent_mm`'s pre-existing defensive
  posture). `raw_build` is the deliberate exception, for two reasons, both load-bearing -- see its own
  docstring: (1) `_y_extent_mm` is called FROM WITHIN `instance_world_offsets`'s own resolution loop,
  so it cannot go through `placed_solid`/`world_bbox` (both call `instance_world_offsets` themselves)
  without recursing infinitely; (2) `validate.py::_placed` needs to keep telling apart "nothing to
  build here" (silently skip -- e.g. an assembly-template MASTER node legitimately has no
  `geometry_builder` of its own) from "the build itself blew up" (a real `degeneracy` error carrying
  the exception's message, which is what makes `ok=False`) -- a function that swallows every failure
  into a bare `None` can't preserve that distinction, and collapsing it would make a genuinely broken
  part silently invisible to validation instead of a reported, `ok`-flipping error.

- **No `build123d.ConvexPolyhedron`.** `constraints/kernel-linux.txt` pins `build123d==0.10.0` (matches
  the Windows dev box per that file's own comment -- confirmed installed here: `hasattr(build123d,
  "ConvexPolyhedron")` is `False`). `ConvexPolyhedron` is a later build123d addition than the version
  actually pinned/running in this repo, so `group_convex_hull` below does not use it. Instead:
  `scipy.spatial.ConvexHull` (already a pinned dependency in the same constraints file, for
  py_gearworks) computes the hull's facets from a point cloud, and this module sews those triangular
  facets into a real build123d `Solid` via `Wire.make_polygon` -> `Face` -> `Shell` -> `Solid` -- a
  general construction path, verified live against the pinned build123d, not a one-off hack.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Sequence

from packages.subsystems import get_subsystem
from packages.subsystems.assembly import instance_world_offsets

if TYPE_CHECKING:
    from build123d import Solid

    from packages.ledger.schema import MasterParametricLedger

_logger = logging.getLogger(__name__)

# (min xyz, max xyz) -- the exact shape `validate.py`'s self-check has used since it first shipped.
# Lives here, not in validate.py: see this module's own docstring for why (avoids an import cycle).
BBox = tuple[tuple[float, float, float], tuple[float, float, float]]

# Point-cloud density feeding group_convex_hull's tessellation. Tighter than blueprint.py's 1.5mm
# silhouette tolerance (an outline can be coarse; an envelope hull that Phase 1/2 size a housing from
# should hug the real part shapes more closely) but coarse enough that even a many-part group keeps
# qhull's input point count -- and therefore build time -- reasonable.
_HULL_TESSELLATION_MM = 1.0


def raw_build(
    ledger: "MasterParametricLedger", instance_id: str, *, allow_kernel_build: bool = True,
) -> Optional[object]:
    """`instance_id`'s geometry via its subsystem's `geometry_builder`, UNPLACED -- no rotation, no
    translation, just the raw solid centered on its own local origin (whatever `Namespace`-driven
    `Subsystem.build` produced). Returns `None` for every outcome every existing call site already
    treated as an unremarkable "nothing to build here, keep going": `allow_kernel_build=False`, an
    instance id absent from `ledger.instances`, a subsystem whose `geometry_builder` is `None` (an
    assembly-template MASTER node deliberately has no geometry of its own -- see
    `Subsystem.assembly_children`'s own docstring), or a `geometry_builder` call that itself returns
    `None`.

    Deliberately does NOT catch a `geometry_builder` call that RAISES -- that propagates to the
    caller. See this module's own docstring for why: `assembly.py::_y_extent_mm` and
    `validate.py::_placed` both call this directly (not `placed_solid`/`world_bbox` below) and keep
    their OWN try/except around it, unchanged from before this module existed, specifically so this
    one function's raise-through behavior can't silently change either of their existing semantics."""
    if not allow_kernel_build:
        return None
    inst = ledger.instances.get(instance_id)
    if inst is None:
        return None
    builder = get_subsystem(inst.subsystem_type).geometry_builder
    if builder is None:
        return None
    part = builder(ledger, instance_id)
    if part is None:
        return None
    return part.solid


def placed_solid(
    ledger: "MasterParametricLedger", instance_id: str, *, allow_kernel_build: bool = True,
    offsets: Optional[dict[str, tuple[float, float, float]]] = None,
) -> Optional["Solid"]:
    """`instance_id`'s geometry, WORLD-placed: `raw_build(...)` above, then rotated by its own
    `Transform` (`bd.Rotation(rx,ry,rz)`, if any) and translated by its resolved
    `instance_world_offsets(...)` offset (`bd.Pos(x,y,z)`) -- the exact build -> rotate -> translate
    sequence that was, before this module existed, independently duplicated in
    `validate.py::_placed` and `blueprint.py::_placed_triangles` (and, minus the placement step,
    `assembly.py::_y_extent_mm` -- see `raw_build`'s docstring for why that one stays separate).

    `offsets` (2026-08-05, perf fix): `instance_world_offsets(...)` is itself O(N) work over the
    WHOLE ledger (it resolves every instance, including one real kernel build per auto-laid-out
    sibling via `_y_extent_mm` -- see that function's docstring), so recomputing it fresh on every
    single-instance call turns any per-instance loop over N instances into O(N^2) real OCCT builds
    -- confirmed live (5 instances -> 30 builds, 10 -> 110, 20 -> 420, matching N^2+N) and NOT just a
    latent risk, since `group_world_bbox`/`group_convex_hull` below (and `blueprint.py`'s
    `_placed_triangles`) do exactly that. Pass a dict already computed by a batch caller (once, up
    front) to skip this function's own `instance_world_offsets` call entirely and use that instead.
    `None` (default) preserves this function's original standalone behaviour -- compute the offsets
    itself, exactly once, for this one call.

    Returns `None` on ANY failure -- an unknown instance, no geometry_builder, a build/rotate/
    translate that raises -- and NEVER raises itself, so one bad instance can't crash a caller
    iterating a whole ledger (`group_world_bbox`/`group_convex_hull` below rely on exactly this)."""
    try:
        solid = raw_build(ledger, instance_id, allow_kernel_build=allow_kernel_build)
        if solid is None:
            return None
        import build123d as bd

        inst = ledger.instances[instance_id]
        rx = ry = rz = 0.0
        if inst.transform is not None:
            rx, ry, rz = inst.transform.rx_deg, inst.transform.ry_deg, inst.transform.rz_deg
        if rx or ry or rz:
            solid = bd.Rotation(rx, ry, rz) * solid
        if offsets is None:
            offsets = instance_world_offsets(ledger, allow_kernel_build=allow_kernel_build)
        ox, oy, oz = offsets.get(instance_id, (0.0, 0.0, 0.0))
        solid = bd.Pos(ox, oy, oz) * solid
        return solid
    except Exception:
        _logger.exception("geometry_query: %s failed to build/place", instance_id)
        return None


def world_bbox(
    ledger: "MasterParametricLedger", instance_id: str, *, allow_kernel_build: bool = True,
    offsets: Optional[dict[str, tuple[float, float, float]]] = None,
) -> Optional[BBox]:
    """`placed_solid(...)`'s bounding box, reshaped to `BBox` (`(min_xyz, max_xyz)`). `None` under the
    exact same conditions `placed_solid` returns `None` (never raises). `offsets`: see
    `placed_solid`'s own docstring -- threaded straight through so a batch caller (e.g.
    `group_world_bbox` below) can compute `instance_world_offsets` ONCE and reuse it across every
    member instead of paying for it again per instance."""
    solid = placed_solid(ledger, instance_id, allow_kernel_build=allow_kernel_build, offsets=offsets)
    if solid is None:
        return None
    bb = solid.bounding_box()
    return ((bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z))


def group_world_bbox(
    ledger: "MasterParametricLedger", instance_ids: Sequence[str], *, allow_kernel_build: bool = True,
) -> Optional[BBox]:
    """The union AABB of every member's `world_bbox` -- pure Python min/max fold, no new OCCT op once
    the per-instance boxes exist. Skips a member whose `world_bbox` returns `None` (one bad/unbuildable
    instance must not fail the whole group's envelope) rather than propagating the failure; returns
    `None` only if EVERY member fails.

    2026-08-05 perf fix: `instance_world_offsets(ledger, ...)` is computed ONCE here, up front, and
    threaded through every member's `world_bbox` call via its `offsets` parameter -- not recomputed
    per member. Before this fix, each `world_bbox` call recomputed offsets for the WHOLE ledger
    internally, turning this loop's O(N) member iteration into O(N^2) real OCCT builds (confirmed
    live: 5 members -> 30 builds, matching N^2+N)."""
    offsets = instance_world_offsets(ledger, allow_kernel_build=allow_kernel_build)
    boxes: list[BBox] = []
    for iid in instance_ids:
        b = world_bbox(ledger, iid, allow_kernel_build=allow_kernel_build, offsets=offsets)
        if b is not None:
            boxes.append(b)
    if not boxes:
        return None
    min_x = min(b[0][0] for b in boxes)
    min_y = min(b[0][1] for b in boxes)
    min_z = min(b[0][2] for b in boxes)
    max_x = max(b[1][0] for b in boxes)
    max_y = max(b[1][1] for b in boxes)
    max_z = max(b[1][2] for b in boxes)
    return ((min_x, min_y, min_z), (max_x, max_y, max_z))


def group_convex_hull(
    ledger: "MasterParametricLedger", instance_ids: Sequence[str], *, allow_kernel_build: bool = True,
) -> Optional["Solid"]:
    """A REAL SOLID convex hull enclosing every member's placed geometry -- the mechanism a later
    phase of the gearbox-housing initiative derives a housing envelope FROM (a shape that follows the
    actual built parts, not an independently-guessed box). See this module's own docstring for why
    this is built on `scipy.spatial.ConvexHull` + a sewn `Wire`/`Face`/`Shell`/`Solid` rather than
    `build123d.ConvexPolyhedron` (not present in the pinned build123d==0.10.0).

    Point cloud: TESSELLATED VERTICES of each member's `placed_solid` (not bbox corners) --
    deliberate tradeoff. Tessellated vertices make the hull follow the real part shapes: a hull
    around two meshed gears comes out gear-shaped-ish, not a fat rectangle around their combined
    bbox, at the cost of feeding qhull more input points (still cheap -- qhull's own hull-vertex
    output is a small fraction of a many-thousand-point tessellation). Bbox corners would be cheaper
    but far coarser, defeating the point of deriving an envelope from the ACTUAL geometry rather than
    another guessed box.

    Returns `None` if fewer than 4 points are available (can't span a 3D hull), if every available
    point is coplanar (`scipy.spatial.ConvexHull` raises `QhullError`, a `RuntimeError` subclass, for
    a degenerate/flat input -- caught same as any other construction failure), or if sewing the
    facets into a solid raises for any other reason. Never raises itself -- one degenerate group must
    not crash a caller.

    2026-08-05 perf fix: same `instance_world_offsets` computed ONCE up front and threaded through
    every member's `placed_solid` call as `group_world_bbox` above does -- see its docstring for why
    (without this, this loop was O(N^2) real OCCT builds, not O(N))."""
    offsets = instance_world_offsets(ledger, allow_kernel_build=allow_kernel_build)
    points: list[tuple[float, float, float]] = []
    for iid in instance_ids:
        solid = placed_solid(ledger, iid, allow_kernel_build=allow_kernel_build, offsets=offsets)
        if solid is None:
            continue
        try:
            verts, _tris = solid.tessellate(_HULL_TESSELLATION_MM)
            points.extend((v.X, v.Y, v.Z) for v in verts)
        except Exception:
            _logger.exception("geometry_query: %s failed to tessellate for a group hull", iid)
    if len(points) < 4:
        return None
    try:
        import build123d as bd
        from scipy.spatial import ConvexHull

        hull = ConvexHull(points)
        faces = []
        for simplex in hull.simplices:
            triangle = [tuple(hull.points[i]) for i in simplex]
            wire = bd.Wire.make_polygon(triangle, close=True)
            faces.append(bd.Face(wire))
        shell = bd.Shell(faces)
        solid = bd.Solid(shell)
        if not solid.is_valid:
            solid = solid.fix()
        return solid
    except Exception:
        _logger.exception(
            "geometry_query: failed to build a convex hull over %d instance(s)", len(instance_ids))
        return None
