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
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from packages.subsystems import get_subsystem
from packages.subsystems.compose import compose, place

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger
    from packages.truth_plane.regen.templated import TaggedPart

_logger = logging.getLogger(__name__)

# Auto-layout tuning (Phase G): a fixed gap between successive auto-placed siblings, and a fallback
# spacing used when an instance's real Y-extent can't be measured (no geometry_builder, or the build
# fails) — auto-layout must degrade gracefully, never crash the whole computation over one instance.
_AUTO_LAYOUT_GAP_MM = 15.0
_FALLBACK_SPACING_MM = 40.0


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
        builder = get_subsystem(inst.subsystem_type).geometry_builder
        if builder is None:
            return _FALLBACK_SPACING_MM
        part = builder(ledger, instance_id)
        if part is None:
            return _FALLBACK_SPACING_MM
        return float(part.solid.bounding_box().size.Y)
    except Exception:
        _logger.exception("auto-layout: %s (%s) failed to build; falling back to %.0fmm spacing",
                           instance_id, inst.subsystem_type, _FALLBACK_SPACING_MM)
        return _FALLBACK_SPACING_MM


def instance_world_offsets(
    ledger: "MasterParametricLedger", *, allow_kernel_build: bool = True,
) -> dict[str, tuple[float, float, float]]:
    """Every instance id -> its (x_mm, y_mm, z_mm) WORLD-SPACE translation offset.

    `allow_kernel_build` (2026-07-21) is threaded straight through to every `_y_extent_mm` call
    below (see its own docstring) -- `resolve_placements` (the connection-mate path) is separately
    confirmed closed-form/OCCT-free (pure param arithmetic over each interface's declared `Frame`
    callable), so it needs no such gate; only the auto-layout extent lookup ever touches a real
    geometry_builder.

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
    # Y-position of the far edge already claimed in a (parent, is_airframe_defining) lane (HALF the
    # parent's own extent once a real parent's first child is placed; unset until then for the
    # top-level stack, whose first instance in a lane is special-cased straight to Y=0 — see the
    # branches below), keyed by (parent id, is this instance an airframe-defining body) — see the
    # 2026-07-20 note above for why this needs to be two lanes, not one.
    auto_cursor_by_parent: dict[tuple[Optional[str], bool], float] = {}

    def resolve(instance_id: str) -> tuple[float, float, float]:
        if instance_id in offsets:
            return offsets[instance_id]
        if instance_id in mated:
            t = mated[instance_id]
            offsets[instance_id] = (t.x_mm, t.y_mm, t.z_mm)  # absolute world placement from the mate solver
            return offsets[instance_id]
        inst = ledger.instances[instance_id]
        parent_id = inst.parent_id
        px, py, pz = resolve(parent_id) if parent_id is not None else (0.0, 0.0, 0.0)
        if inst.transform is not None:
            t = inst.transform
            local = (t.x_mm, t.y_mm, t.z_mm)
        else:
            cursor_key = (parent_id, _is_airframe_defining(ledger, instance_id))
            this_extent = _y_extent_mm(ledger, instance_id, allow_kernel_build=allow_kernel_build)
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
                far_edge_claimed = _y_extent_mm(
                    ledger, parent_id, allow_kernel_build=allow_kernel_build) / 2.0
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
