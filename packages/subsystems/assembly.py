"""Phase G — assembly composition (2026-07-03).

Today a project's ledger holds a TREE of `Instance`s (`packages/ledger/schema.py`) but nothing
renders more than the single active instance's geometry. This module is the pure composition layer
that turns the whole tree into ONE positioned scene:

- `instance_world_offsets(ledger)` resolves every instance's world-space translation, recursively
  composing parent offsets down the `parent_id` chain. An instance with an explicit `Transform` is
  honored as-is (relative to its parent's resolved offset); an instance with `transform is None` is
  auto-laid-out along +Y so a freshly-created multi-instance project never overlaps with zero manual
  configuration. This is reusable outside geometry (e.g. mass/CG telemetry) — it returns plain floats.
- `render_assembly(ledger)` builds every instance's geometry, positions it via the offsets above (plus
  its own rotation, if any), and unions everything into one `TaggedPart` via `compose.py`'s
  `place()`/`compose()`, namespaced by instance id.

Pure composition only: no I/O, no HTTP, no `packages.transport` awareness. Matches `compose.py`'s
convention of never importing build123d at module scope — it's pulled in lazily (via the registered
subsystems' geometry_builder, and via `place()`/`compose()`) so importing this module never drags in
the kernel for pure-Python callers (schema validation, tests without build123d, etc).

Phase 1 addendum (2026-08-06, gearbox-housing-generation initiative): `instance_world_offsets` also
gives each UNANCHORED connected component of `placement.py`'s connection graph (a `Connection`-joined
group with no member carrying an explicit `transform`, e.g. a mesh-connected gear pair) its own
auto-layout slot via a small 2D shelf/row packer (`_ComponentShelfPacker` below) — fixing a confirmed
bug where every such component landed at the SAME shared world origin independently and collided. See
`_component_shifts`'s own docstring for the mechanism, and `placement.py::unanchored_components` for
which components qualify.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Optional, Sequence

from packages.subsystems import get_subsystem
from packages.subsystems.compose import compose, place

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger, Transform
    from packages.truth_plane.regen.templated import TaggedPart

_logger = logging.getLogger(__name__)

# Auto-layout tuning (Phase G): a fixed gap between successive auto-placed siblings, and a fallback
# spacing used when an instance's real Y-extent can't be measured (no geometry_builder, or the build
# fails) — auto-layout must degrade gracefully, never crash the whole computation over one instance.
_AUTO_LAYOUT_GAP_MM = 15.0
_FALLBACK_SPACING_MM = 40.0

# (min xyz, max xyz) -- a LOCAL type alias mirroring geometry_query.py's own `BBox`, deliberately not
# imported from there: this module must not import geometry_query at module scope (geometry_query.py
# imports `instance_world_offsets` FROM this module at ITS top level -- a module-level import back
# here would be a straight import cycle, the exact same hazard `_y_extent_mm`'s own docstring already
# documents for `raw_build`/`placed_solid`/`world_bbox`).
_BBox = tuple[tuple[float, float, float], tuple[float, float, float]]


def _is_airframe_defining(ledger: "MasterParametricLedger", instance_id: str) -> bool:
    """True for a wing/fuselage-class body that sets the vehicle's own outer mold line (the same
    flag `packages/agents/prompt_builder.py`'s airframe-pacing section reads) — used here to give
    such a body its OWN auto-layout lane, separate from ordinary system/mounting parts. See
    `instance_world_offsets`'s 2026-07-20 docstring note for why."""
    inst = ledger.instances[instance_id]
    return get_subsystem(inst.subsystem_type).is_airframe_defining


def _y_extent_mm(ledger: "MasterParametricLedger", instance_id: str, *,
                  allow_kernel_build: bool = True) -> float:
    """Build `instance_id`'s geometry ONCE and read its bounding box's Y-span, for auto-layout
    spacing. Falls back to `_FALLBACK_SPACING_MM` if the instance's subsystem has no
    `geometry_builder`, the build returns None, or building raises for any reason.

    `allow_kernel_build` (2026-07-21, foundations-audit follow-up): False on the INTERACTIVE plane
    (`packages/transport/app.py::_telemetry`, the WS mutation response's telemetry_delta) — a real
    geometry_builder call is genuine OCCT kernel work, which Inversion #2 (packages/CLAUDE.md)
    forbids there outright, timeout or not (unlike `/mesh`'s `_bounded_geometry_build`, which bounds
    but doesn't forbid a kernel-tier build). False means this ALWAYS returns `_FALLBACK_SPACING_MM`
    for an instance with no analytic extent available -- the same honest "can't tell, use the
    fallback" outcome auto-layout already produces today for a subsystem with no geometry_builder,
    just applied more broadly. True (default) preserves the exact prior behavior for kernel-regen-
    tier callers (`render_assembly`, `list_pickable_features`) -- both already run through
    `_bounded_geometry_build` as a whole at the HTTP layer, so a real build here is bounded, not raw."""
    inst = ledger.instances[instance_id]
    if not allow_kernel_build:
        return _FALLBACK_SPACING_MM
    try:
        # geometry_query.raw_build (2026-08-05, gearbox-housing Phase 0) shares the get-builder/
        # build/defend-against-None boilerplate this function used to inline with validate.py's and
        # blueprint.py's own per-instance build steps. Deliberately NOT geometry_query.placed_solid/
        # world_bbox: both call instance_world_offsets(...) internally, and THIS function is itself
        # called FROM WITHIN instance_world_offsets's own resolution loop below (to size an
        # auto-layout slot before this instance's own world offset exists yet) -- going through
        # either would recurse infinitely. Lazily imported (matching this module's own
        # `resolve_placements` import inside instance_world_offsets just below) because
        # geometry_query.py imports instance_world_offsets FROM this module at ITS top level; a
        # module-level import here would be a straight import cycle.
        from packages.subsystems.geometry_query import raw_build
        solid = raw_build(ledger, instance_id, allow_kernel_build=allow_kernel_build)
        if solid is None:
            return _FALLBACK_SPACING_MM
        return float(solid.bounding_box().size.Y)
    except Exception:
        _logger.exception("auto-layout: %s (%s) failed to build; falling back to %.0fmm spacing",
                           instance_id, inst.subsystem_type, _FALLBACK_SPACING_MM)
        return _FALLBACK_SPACING_MM


# ---------------------------------------------------------------------------------------------------
# Component-level auto-layout (Phase 1, 2026-08-06, gearbox-housing-generation initiative) -- gives
# each UNANCHORED connected component (`placement.py::unanchored_components`) its OWN 2D shelf/row
# slot, instead of colliding with every other unanchored component at the shared (0,0,0)
# `resolve_placements` seeds its datum at for lack of an anchor (the confirmed bug this phase fixes:
# two mesh-connected gear pairs, neither anchored, used to land exactly on top of each other -- their
# resolved world bboxes came out literally identical).
#
# Deliberately a SEPARATE mechanism from the per-instance `auto_cursor_by_parent` lane-cursor below --
# NOT a generalization of it -- so the existing per-instance auto-layout behavior for genuinely
# unconnected instances (no Connection at all) stays provably, byte-for-byte unchanged (see this
# phase's own tests). The FIRST unanchored component (lowest member id, matching
# `unanchored_components`'s own ordering) is likewise left COMPLETELY UNSHIFTED -- it has nothing to
# collide with yet, so the pre-existing single-mesh-pair behavior (datum at the identity
# `resolve_placements` already puts it at) is preserved exactly; only the SECOND and later components
# get packed into a slot that avoids the first one's (and each other's) footprint.
# ---------------------------------------------------------------------------------------------------

_COMPONENT_SLOT_GAP_MM = _AUTO_LAYOUT_GAP_MM
# Row-wrap threshold for the shelf packer below -- keeps a many-component gearbox from stringing every
# component out along a single axis (the ~900mm-sprawl half of this phase's bug) by wrapping to a new
# row once a row gets this wide, at the cost of not being a true bin-packing optimum. A tunable
# heuristic constant, same spirit as `_AUTO_LAYOUT_GAP_MM`/`_FALLBACK_SPACING_MM` above -- "do not
# over-engineer a general bin-packing solver" (this phase's own scope).
_COMPONENT_SHELF_ROW_WIDTH_MM = 400.0


class _ComponentShelfPacker:
    """A deterministic 2D shelf/row bin packer -- "a simple 2D shelf/row packer over each component's
    real (width, depth) extent", per this phase's own scope (no rotation, no best-fit, just enough to
    turn "everything strung out along one 900mm line" into a compact 2D grid).

    `occupy_rect(...)` marks an ALREADY-PLACED rectangle (the first, deliberately-unshifted component)
    as consuming the packer's first row slot, so `place(...)` calls for later components pack AROUND
    it. `place(width_mm, depth_mm)` reserves a NEW slot (wrapping to a new row below the current one
    once the current row would exceed `_COMPONENT_SHELF_ROW_WIDTH_MM`) and returns that slot's CENTER
    `(cx, cy)` -- the caller turns that into a per-member world-offset shift (see
    `instance_world_offsets` below)."""

    def __init__(self, gap_mm: float = _COMPONENT_SLOT_GAP_MM,
                 row_width_limit_mm: float = _COMPONENT_SHELF_ROW_WIDTH_MM):
        self._gap = gap_mm
        self._row_limit = row_width_limit_mm
        self._row_far_x = 0.0     # far X-edge already claimed in the CURRENT row
        self._row_y = 0.0         # near Y-edge (baseline) of the CURRENT row
        self._row_depth = 0.0     # max depth (Y-extent) among items placed in the CURRENT row so far
        self._row_has_items = False

    def occupy_rect(self, min_x: float, min_y: float, max_x: float, max_y: float) -> None:
        """Pre-occupy the packer's first row with an already-placed (unshifted) rectangle. Must be
        called at most once, before any `place(...)` call."""
        self._row_y = min_y
        self._row_far_x = max_x
        self._row_depth = max_y - min_y
        self._row_has_items = True

    def place(self, width_mm: float, depth_mm: float) -> tuple[float, float]:
        if self._row_has_items and self._row_far_x + self._gap + width_mm > self._row_limit:
            # wrap to a new row/shelf below the current one
            self._row_y += self._row_depth + self._gap
            self._row_far_x = 0.0
            self._row_depth = 0.0
            self._row_has_items = False
        near_x = self._row_far_x + (self._gap if self._row_has_items else 0.0)
        cx = near_x + width_mm / 2.0
        cy = self._row_y + depth_mm / 2.0
        self._row_far_x = near_x + width_mm
        self._row_depth = max(self._row_depth, depth_mm)
        self._row_has_items = True
        return (cx, cy)


def _component_local_bbox_mm(
    ledger: "MasterParametricLedger", member_ids: Sequence[str], mated: dict[str, "Transform"], *,
    allow_kernel_build: bool = True,
) -> Optional[_BBox]:
    """The union bounding box of an UNANCHORED connected component's members, in the component's own
    LOCAL frame (i.e. as if its datum sat at world origin -- exactly where `resolve_placements` seeds
    an unanchored component's datum today) -- the REAL combined footprint the packer above needs to
    size this component's own auto-layout slot, mirroring `geometry_query.group_world_bbox`'s
    bbox-union math but DELIBERATELY NOT calling it: `group_world_bbox` computes its own
    `instance_world_offsets(ledger, ...)` internally, and this function is itself called FROM WITHIN
    `instance_world_offsets`'s own resolution loop below (to size a component's slot before that
    component's own world offset exists yet) -- going through `group_world_bbox` (or
    `placed_solid`/`world_bbox`) here would recurse infinitely (the SAME hazard `_y_extent_mm`'s own
    docstring already documents for the single-instance case, one level up: a GROUP of instances
    instead of one).

    Each member's RAW (unplaced, own-local-origin) solid comes from `raw_build` -- the same
    recursion-safe primitive `_y_extent_mm` uses -- then is shifted by `mated[member]`'s TRANSLATION
    only (mate-solved members carry no rotation: v1 mate solving is translation-only, see
    `placement.py`'s own module docstring). For an UNANCHORED component this translation is already
    relative to the component's own local origin (its datum's seed IS identity, per
    `resolve_placements`'s own datum-selection rule), so no extra math is needed to make it "local".

    Returns `None` if every member fails to build (absent from `mated`, `raw_build` raising, or
    returning `None`) -- the caller falls back to a fixed default footprint, exactly as `_y_extent_mm`
    falls back to `_FALLBACK_SPACING_MM` for a single unbuildable instance."""
    from packages.subsystems.geometry_query import raw_build

    min_x = min_y = min_z = math.inf
    max_x = max_y = max_z = -math.inf
    for member_id in member_ids:
        t = mated.get(member_id)
        if t is None:
            continue
        try:
            solid = raw_build(ledger, member_id, allow_kernel_build=allow_kernel_build)
        except Exception:
            _logger.exception(
                "component auto-layout: %s failed to build; excluding from footprint", member_id)
            continue
        if solid is None:
            continue
        bb = solid.bounding_box()
        min_x = min(min_x, bb.min.X + t.x_mm)
        max_x = max(max_x, bb.max.X + t.x_mm)
        min_y = min(min_y, bb.min.Y + t.y_mm)
        max_y = max(max_y, bb.max.Y + t.y_mm)
        min_z = min(min_z, bb.min.Z + t.z_mm)
        max_z = max(max_z, bb.max.Z + t.z_mm)
    if min_x == math.inf:
        return None
    return ((min_x, min_y, min_z), (max_x, max_y, max_z))


def _component_shifts(
    ledger: "MasterParametricLedger", mated: dict[str, "Transform"], *, allow_kernel_build: bool = True,
) -> dict[str, tuple[float, float, float]]:
    """`{instance_id: (shift_x, shift_y, shift_z)}` for every member of every UNANCHORED connected
    component (empty dict if there are none, or only one -- see below) -- added to that member's
    `mated[...]` translation in `instance_world_offsets`'s own `resolve(...)` below to give each
    component its own auto-layout slot instead of colliding at a shared origin.

    The FIRST component (`placement.py::unanchored_components`'s own ordering: lowest member id) is
    deliberately given a shift of exactly zero for every member and instead PRE-OCCUPIES the packer's
    first row slot via `occupy_rect` -- preserving the pre-existing single-component behavior
    (`resolve_placements`'s own identity-seeded datum) bit-for-bit. Only the SECOND and later
    components are actually repositioned, into slots that avoid the first one's (and each other's)
    real footprint."""
    from packages.subsystems.placement import unanchored_components

    components = unanchored_components(ledger)
    shifts: dict[str, tuple[float, float, float]] = {}
    if len(components) <= 1:
        return shifts  # nothing to collide with -- zero behavior change (see docstring above)

    packer = _ComponentShelfPacker()
    first_bbox = _component_local_bbox_mm(
        ledger, components[0], mated, allow_kernel_build=allow_kernel_build)
    if first_bbox is not None:
        (fx0, fy0, _fz0), (fx1, fy1, _fz1) = first_bbox
        packer.occupy_rect(fx0, fy0, fx1, fy1)
    else:
        packer.occupy_rect(
            -_FALLBACK_SPACING_MM / 2.0, -_FALLBACK_SPACING_MM / 2.0,
            _FALLBACK_SPACING_MM / 2.0, _FALLBACK_SPACING_MM / 2.0)

    for member_ids in components[1:]:
        bbox = _component_local_bbox_mm(ledger, member_ids, mated, allow_kernel_build=allow_kernel_build)
        if bbox is not None:
            (x0, y0, _z0), (x1, y1, _z1) = bbox
            width, depth = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
            local_cx, local_cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        else:
            width = depth = _FALLBACK_SPACING_MM
            local_cx = local_cy = 0.0
        cx, cy = packer.place(width, depth)
        shift = (cx - local_cx, cy - local_cy, 0.0)
        for member_id in member_ids:
            shifts[member_id] = shift
    return shifts


def instance_world_offsets(
    ledger: "MasterParametricLedger", *, allow_kernel_build: bool = True,
    extent_overrides: Optional[dict[str, float]] = None,
) -> dict[str, tuple[float, float, float]]:
    """Every instance id -> its (x_mm, y_mm, z_mm) WORLD-SPACE translation offset.

    `allow_kernel_build` (2026-07-21) is threaded straight through to every `_y_extent_mm` call
    below (see its own docstring) -- `resolve_placements` (the connection-mate path) is separately
    confirmed closed-form/OCCT-free (pure param arithmetic over each interface's declared `Frame`
    callable), so it needs no such gate; only the auto-layout extent lookup ever touches a real
    geometry_builder.

    `extent_overrides` (2026-08-06, gearbox-housing-generation initiative Phase 5 -- confirmed defect
    fix): `{instance_id: y_extent_mm}` -- when an instance id appears here, its auto-layout Y-extent is
    taken from this dict directly instead of calling `_y_extent_mm` (i.e. instead of a real
    `raw_build`/`geometry_builder` call for that ONE instance). `None` (default, every pre-existing
    caller) is zero behavior change. The one intended caller: a subsystem's OWN `build_with_ledger`
    hook (`derived_housing.py`'s `_wraps_shaft_axes`/`_housing_world_xy`) needs THIS function's real,
    general cursor-lane resolution to learn its OWN world offset (to place ledger-derived features
    correctly in its LOCAL frame) -- but calling `_y_extent_mm` for that SAME instance would re-enter
    that subsystem's own `build_with_ledger` a second time (infinite recursion, not just a slow path).
    Passing `{that_instance_id: <a params-only, no-build Y-extent>}` here breaks the cycle for exactly
    that one instance while every OTHER instance in the resolution (parents, prior auto-laid-out
    siblings, ...) still resolves through a real build where one is needed -- see `_extent`'s own
    inline comment just below for the exact substitution point.

    Parts are a FLAT set brought into a file (2026-07-04) — there is no root, so a top-level part
    (`parent_id is None`) resolves against the ORIGIN directly, not a root instance's own offset.
    A non-top-level instance (real parenting: assembly-template children, explicit REST parenting)
    with an explicit `transform` uses that transform's (x_mm, y_mm, z_mm) as its offset from its
    PARENT's resolved world offset (added to it) — fully recursive, so arbitrary-depth `parent_id`
    chains resolve correctly. An instance with `transform is None` is auto-laid-out along +Y from
    its siblings (same `parent_id` — `None` for top-level parts, so they're all siblings of each
    other by default): a running cursor per parent (keyed by parent id, or `None` for the top-level
    stack) tracks the far Y-edge of everything ALREADY placed in that lane — not a center. The FIRST
    instance placed in a lane either clears HALF the PARENT's OWN Y-extent (a part is built centered
    on its own local origin, so its body's far edge sits at extent/2, not the full extent) for a real
    parent, or — for the top-level stack, which has no body to clear at all — sits at exactly the
    origin (Y=0). Each auto-placed instance is centered at `cursor + GAP + this instance's OWN
    half-extent`, and the cursor then advances to THIS instance's own far edge (`cursor + GAP + this
    instance's FULL extent`) for whoever is placed next — reserving half of every instance's own
    extent on both its near and far side, so the edge-to-edge gap between any two consecutive
    auto-placed siblings is exactly `GAP`, independent of how their extents compare (2026-08 fix: an
    earlier version centered each instance at `cursor + GAP` with no half-extent term, which only
    ever reserved clearance on ONE side of each part — the real edge-to-edge gap it produced was
    `GAP + (extent_prev - extent_next) / 2`, which went NEGATIVE, i.e. actual 3-D interpenetration,
    the moment a later sibling's extent exceeded the previous one's by more than `2 * GAP`).
    (Siblings that carry an explicit transform were positioned by the user and are not folded into
    this running stack — they don't consume auto-layout "slots".)

    2026-07-20 fix: the cursor is actually keyed by `(parent_id, is_airframe_defining)`, TWO
    independent lanes per parent group, not one. A single shared queue broke completely the moment
    one sibling was an `is_airframe_defining` body (a wing/fuselage-class part, e.g.
    `winged_fuselage`): its Y-extent is its WINGSPAN (a real live repro measured 1100mm), so placing
    it first shoved the ENTIRE REST of the queue out past 1.1 meters before anything else got a
    position — every small system/mounting part ended up clustered tightly against each OTHER but
    uniformly far from the airframe itself (confirmed: a self-check reporting "floats ~553mm from
    the nearest other part" on the fuselage, and a blueprint showing one lone airframe blob plus a
    separate debris cluster). Splitting the cursor gives the (rare, usually singular) airframe-
    defining body its own lane while every non-airframe sibling shares its OWN lane seeded
    independently — so small system parts now cluster near the ORIGIN (i.e. at/inside the airframe
    body's own footprint) instead of past its wingspan. `is_airframe_defining` is False for every
    subsystem except 8 wing/fuselage-class parts, so a project with none of those 8 present (the
    overwhelming common case — brackets, enclosures, rovers, satellites, ...) collapses onto a
    single lane exactly as before: zero behavior change there.
    """
    offsets: dict[str, tuple[float, float, float]] = {}
    # Phase 1 (2026-07-19): a part joined by a typed Connection gets its world translation from the
    # MATE SOLVER (packages/subsystems/placement.py) — computed from the partner's declared interface
    # frame — instead of a hand-set transform or auto-layout. Connection-placed parts short-circuit the
    # parent-chain/auto-layout logic below; everything without a connection is unchanged.
    from packages.subsystems.placement import resolve_placements
    mated = resolve_placements(ledger)  # {instance_id: world Transform}; empty when there are no connections
    # Phase 1 (2026-08-06, gearbox-housing-generation initiative): a per-CONNECTED-COMPONENT rigid
    # shift for every member of an UNANCHORED component beyond the first (see `_component_shifts`'s
    # own docstring) — fixes the confirmed bug where every unanchored component's datum landed at the
    # SAME shared origin `resolve_placements` seeds it at, independently, causing literal
    # interpenetration between e.g. two unrelated mesh-connected gear pairs. Empty dict (zero added
    # cost, zero behavior change) whenever there are 0 or 1 unanchored components — the overwhelming
    # common case, and the exact case every pre-existing connection-placement test already covers.
    component_shift = _component_shifts(ledger, mated, allow_kernel_build=allow_kernel_build) if mated else {}
    # Y-position of the far edge already claimed in a (parent, is_airframe_defining) lane (HALF the
    # parent's own extent once a real parent's first child is placed; unset until then for the
    # top-level stack, whose first instance in a lane is special-cased straight to Y=0 — see the
    # branches below), keyed by (parent id, is this instance an airframe-defining body) — see the
    # 2026-07-20 note above for why this needs to be two lanes, not one.
    auto_cursor_by_parent: dict[tuple[Optional[str], bool], float] = {}

    def _extent(iid: str) -> float:
        # `extent_overrides` substitution point (see this function's own docstring) — an override,
        # when present for `iid`, is used INSTEAD of a real `_y_extent_mm`/`raw_build` call for that
        # one instance id; every other id still resolves through a real build where one is needed.
        if extent_overrides is not None and iid in extent_overrides:
            return extent_overrides[iid]
        return _y_extent_mm(ledger, iid, allow_kernel_build=allow_kernel_build)

    def resolve(instance_id: str) -> tuple[float, float, float]:
        if instance_id in offsets:
            return offsets[instance_id]
        if instance_id in mated:
            t = mated[instance_id]
            sx, sy, sz = component_shift.get(instance_id, (0.0, 0.0, 0.0))
            # absolute world placement from the mate solver, plus this instance's component-level
            # auto-layout shift (zero for an anchored component, or the sole/first unanchored one)
            offsets[instance_id] = (t.x_mm + sx, t.y_mm + sy, t.z_mm + sz)
            return offsets[instance_id]
        inst = ledger.instances[instance_id]
        parent_id = inst.parent_id
        px, py, pz = resolve(parent_id) if parent_id is not None else (0.0, 0.0, 0.0)
        if inst.transform is not None:
            t = inst.transform
            local = (t.x_mm, t.y_mm, t.z_mm)
        else:
            cursor_key = (parent_id, _is_airframe_defining(ledger, instance_id))
            this_extent = _extent(instance_id)
            # `cursor` (once known) is the Y-position of the far edge already claimed in this lane —
            # NOT a center. Placing THIS instance a full GAP plus its OWN half-extent past that edge
            # (`cursor + GAP + this_extent / 2`), then advancing the claimed edge to THIS instance's
            # own far edge (`local_y + this_extent / 2`) for whoever is placed next, reserves
            # this_extent/2 on the near side AND this_extent/2 on the far side of every instance — so
            # the edge-to-edge gap between any two consecutive auto-placed siblings is exactly GAP,
            # regardless of how their extents compare (2026-08 fix: an earlier version placed each
            # center at `cursor + GAP`, with no `/2` term — that only ever reserved clearance on ONE
            # side of each part, so the real edge-to-edge gap it produced was
            # `GAP + (extent_prev - extent_next) / 2`, which went NEGATIVE — actual 3-D
            # interpenetration, not just a Y-axis artifact, since every auto-placed instance shares
            # x=0, z=0 — the moment a later sibling's extent exceeded the previous one's by more than
            # `2 * GAP`).
            if cursor_key in auto_cursor_by_parent:
                far_edge_claimed = auto_cursor_by_parent[cursor_key]
                local_y = far_edge_claimed + _AUTO_LAYOUT_GAP_MM + this_extent / 2.0
            elif parent_id is not None:
                # First instance in this lane, under a REAL parent: seed at HALF the parent's own
                # Y-extent. A part is built centered on its own local origin (spans
                # -extent/2 .. +extent/2), so the parent's own body's far edge sits at extent/2, not
                # the full extent (seeding the full extent, as an earlier version did, overshot by
                # another half-extent of unnecessary clearance before the first child).
                far_edge_claimed = _extent(parent_id) / 2.0
                local_y = far_edge_claimed + _AUTO_LAYOUT_GAP_MM + this_extent / 2.0
            else:
                # First instance in this lane, top-level (no parent body to clear at all): its center
                # sits at EXACTLY the origin. Special-cased directly to 0.0 rather than derived via
                # the general `cursor + GAP + this_extent / 2` formula (which would need a seed of
                # `-GAP - this_extent / 2` to land back on 0 algebraically) so this invariant holds
                # bit-for-bit for every this_extent, not just up to floating-point rounding noise from
                # adding this_extent/2 and then subtracting it back out.
                local_y = 0.0
            local = (0.0, local_y, 0.0)
            auto_cursor_by_parent[cursor_key] = local_y + this_extent / 2.0
        world = (px + local[0], py + local[1], pz + local[2])
        offsets[instance_id] = world
        return world

    for instance_id in ledger.instances:
        resolve(instance_id)
    return offsets


def render_assembly(ledger: "MasterParametricLedger") -> "TaggedPart":
    """Compose EVERY instance in `ledger.instances` into one `TaggedPart`, positioned via
    `instance_world_offsets()` (plus each instance's own rotation, if `transform` is set) using
    `compose.py`'s `place()` / `compose()`. Tags are namespaced by instance id. Skips any instance
    whose subsystem has no `geometry_builder`, or whose build raises/returns None — defensive; a
    single broken instance must not take down the whole assembly render."""
    offsets = instance_world_offsets(ledger)
    scope_map: dict[str, "TaggedPart"] = {}
    for instance_id, inst in ledger.instances.items():
        try:
            builder = get_subsystem(inst.subsystem_type).geometry_builder
            if builder is None:
                _logger.warning("assembly render: %s (%s) has no geometry_builder; skipping",
                                 instance_id, inst.subsystem_type)
                continue
            part = builder(ledger, instance_id)
        except Exception:
            # Defensive per-instance isolation is intentional (one broken part must not blank the
            # whole assembly) -- but silently swallowing the exception with no trace anywhere made a
            # real build123d failure indistinguishable from "nothing to render" at every layer above
            # this (HTTP 200 with empty positions/indices, no error surfaced to the chat or the
            # viewport). Logging keeps the isolation but makes the failure diagnosable.
            _logger.exception("assembly render: %s (%s) failed to build; skipping this instance",
                               instance_id, inst.subsystem_type)
            continue
        if part is None:
            _logger.warning("assembly render: %s (%s) geometry_builder returned None; skipping",
                             instance_id, inst.subsystem_type)
            continue
        x, y, z = offsets[instance_id]
        rx = ry = rz = 0.0
        if inst.transform is not None:
            rx, ry, rz = inst.transform.rx_deg, inst.transform.ry_deg, inst.transform.rz_deg
        scope_map[instance_id] = place(part, x=x, y=y, z=z, rx=rx, ry=ry, rz=rz)
    return compose(scope_map)
