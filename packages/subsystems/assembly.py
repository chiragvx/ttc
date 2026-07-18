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


def _y_extent_mm(ledger: "MasterParametricLedger", instance_id: str) -> float:
    """Build `instance_id`'s geometry ONCE and read its bounding box's Y-span, for auto-layout
    spacing. Falls back to `_FALLBACK_SPACING_MM` if the instance's subsystem has no
    `geometry_builder`, the build returns None, or building raises for any reason."""
    inst = ledger.instances[instance_id]
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


def instance_world_offsets(ledger: "MasterParametricLedger") -> dict[str, tuple[float, float, float]]:
    """Every instance id -> its (x_mm, y_mm, z_mm) WORLD-SPACE translation offset.

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
    """
    offsets: dict[str, tuple[float, float, float]] = {}
    # cumulative Y-extent already claimed in a parent's stack (seeded with the parent's OWN extent
    # for a real parent, 0.0 for the top-level stack, then grown by each auto-placed child's
    # extent), keyed by parent id — `None` is the top-level stack's key.
    auto_cursor_by_parent: dict[Optional[str], float] = {}

    def resolve(instance_id: str) -> tuple[float, float, float]:
        if instance_id in offsets:
            return offsets[instance_id]
        inst = ledger.instances[instance_id]
        parent_id = inst.parent_id
        px, py, pz = resolve(parent_id) if parent_id is not None else (0.0, 0.0, 0.0)
        if inst.transform is not None:
            t = inst.transform
            local = (t.x_mm, t.y_mm, t.z_mm)
        else:
            if parent_id not in auto_cursor_by_parent:
                if parent_id is not None:
                    # a REAL parent's own body needs clearing — seed at its Y-extent so the first
                    # child doesn't nest back inside it.
                    auto_cursor_by_parent[parent_id] = _y_extent_mm(ledger, parent_id)
                else:
                    # the top-level stack has no body to clear — seed at -GAP so the formula below
                    # (`cursor + GAP`) places the FIRST top-level part's center at exactly 0, not
                    # gap-offset from nothing. Only the 2nd+ sibling actually needs the gap.
                    auto_cursor_by_parent[parent_id] = -_AUTO_LAYOUT_GAP_MM
            cursor = auto_cursor_by_parent[parent_id]
            # GAP is added before EVERY auto-placed instance (not just the first) — placing this
            # instance's center at cursor+GAP and then reserving cursor+GAP+this_extent for whatever
            # comes next guarantees a real gap between EVERY consecutive pair, regardless of how their
            # extents compare (a bug in an earlier version only gapped the first child from its
            # parent, then packed subsequent siblings back-to-back with center-to-center spacing equal
            # to the PREVIOUS sibling's extent alone — safe only when extents were non-increasing,
            # and capable of overlapping two instances outright otherwise).
            this_extent = _y_extent_mm(ledger, instance_id)
            local = (0.0, cursor + _AUTO_LAYOUT_GAP_MM, 0.0)
            auto_cursor_by_parent[parent_id] = cursor + _AUTO_LAYOUT_GAP_MM + this_extent
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
