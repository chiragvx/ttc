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
    stack) tracks the far Y-edge of everything already placed, seeded with the PARENT's OWN
    Y-extent for a real parent (0 for the top-level stack, since there's no parent body to clear).
    Each auto-placed instance is centered at `cursor + 15mm gap`, and the cursor then advances by
    `gap + this instance's own Y-extent` — so the 15mm gap is inserted before EVERY auto-placed
    instance, which is what actually guarantees no overlap regardless of how consecutive siblings'
    extents compare. (Siblings that carry an explicit transform were positioned by the user and are
    not folded into this running stack — they don't consume auto-layout "slots".)

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
    # cumulative Y-extent already claimed in a (parent, is_airframe_defining) lane (seeded with the
    # parent's OWN extent for a real parent, -GAP for the top-level stack), keyed by
    # (parent id, is this instance an airframe-defining body) — see the 2026-07-20 note above for why
    # this needs to be two lanes, not one.
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
            if cursor_key not in auto_cursor_by_parent:
                if parent_id is not None:
                    # a REAL parent's own body needs clearing — seed at its Y-extent so the first
                    # child doesn't nest back inside it.
                    auto_cursor_by_parent[cursor_key] = _y_extent_mm(
                        ledger, parent_id, allow_kernel_build=allow_kernel_build)
                else:
                    # the top-level stack has no body to clear — seed at -GAP so the formula below
                    # (`cursor + GAP`) places the FIRST top-level part's center at exactly 0, not
                    # gap-offset from nothing. Only the 2nd+ sibling actually needs the gap.
                    auto_cursor_by_parent[cursor_key] = -_AUTO_LAYOUT_GAP_MM
            cursor = auto_cursor_by_parent[cursor_key]
            # GAP is added before EVERY auto-placed instance (not just the first) — placing this
            # instance's center at cursor+GAP and then reserving cursor+GAP+this_extent for whatever
            # comes next guarantees a real gap between EVERY consecutive pair, regardless of how their
            # extents compare (a bug in an earlier version only gapped the first child from its
            # parent, then packed subsequent siblings back-to-back with center-to-center spacing equal
            # to the PREVIOUS sibling's extent alone — safe only when extents were non-increasing,
            # and capable of overlapping two instances outright otherwise).
            this_extent = _y_extent_mm(ledger, instance_id, allow_kernel_build=allow_kernel_build)
            local = (0.0, cursor + _AUTO_LAYOUT_GAP_MM, 0.0)
            auto_cursor_by_parent[cursor_key] = cursor + _AUTO_LAYOUT_GAP_MM + this_extent
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
