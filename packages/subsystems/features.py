"""Pickable feature list (Phase 3 HUD groundwork, 2026-07-03).

The product spec (`prd-27-8.14/prd4.md`, Phase 3) wants clicking a component in the viewport to
anchor a "context-aware floating HUD" to that specific component. The precise version of that needs
OCCT topological identity (a specialist-gated, not-yet-built capability — see
`packages/truth_plane/regen/templated.py`'s module docstring). This module is a deliberately ROUGH
stand-in that needs none of that: every subsystem already bakes stable, generator-authored TAGS into
its geometry (`hole[0].bore`, `mount[1].bore`, ...), and many of those tags carry a "center" position
computed as plain arithmetic from the subsystem's own params. `list_pickable_features` walks the
whole ledger's instance tree, collects every tag with a usable position, and reports its WORLD-SPACE
point — the data a "click near a feature" HUD can search over.

Honest limitations (documented, not silently "fixed" by inventing precision the data doesn't
support):
- Only a TRANSLATION offset is applied (via `assembly.instance_world_offsets`) — an instance's own
  ROTATION is not applied to the tag's local point.
- A composite subsystem's own internal sub-part placements (e.g. `standoff_frame`'s legs, positioned
  via `compose.py`'s `place()`) are not further corrected — the tag's stored "center" (if any) is
  already in the composite's own top-level local frame, not re-derived from `_placement`.

Pure composition only: no I/O, no HTTP, no `packages.transport` awareness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from packages.subsystems import get_subsystem
from packages.subsystems.assembly import instance_world_offsets

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger


def list_pickable_features(ledger: "MasterParametricLedger") -> list[dict]:
    """Every geometric feature (tag) across the WHOLE ledger with a usable WORLD-SPACE position.
    For each instance: build its geometry ONCE via its subsystem's geometry_builder(ledger,
    instance_id) (skip the instance entirely -- do not raise -- if geometry_builder is None, the
    build raises, or returns None: mirrors packages/subsystems/assembly.py's own defensive
    convention for exactly this situation). For each (tag_name, meta) in that instance's
    TaggedPart.tags: skip if tag_name == "_placement" (positioning metadata, not a real feature) or
    if "center" not in meta (whole-body "solid"/"pocket"-style tags with no position -- these
    aren't "specific components" in the PRD's sense, they're the whole part). meta["center"] is a
    2-or-3-element list [x, y] or [x, y, z] in the instance's OWN LOCAL frame -- pad a missing Z
    with 0.0. Add the instance's WORLD offset (from instance_world_offsets(ledger), called ONCE,
    not per-instance -- it's not free) to get the world-space point.

    Returns a flat list of {"instance_id": str, "tag": str, "point": [x, y, z], "meta": dict} one
    entry per pickable feature. Do NOT call instance_world_offsets or any instance's
    geometry_builder more than once per instance -- both do real work (geometry_builder builds a
    real build123d solid); keep this a single pass over ledger.instances.
    """
    offsets = instance_world_offsets(ledger)
    features: list[dict] = []
    for instance_id, inst in ledger.instances.items():
        try:
            builder = get_subsystem(inst.subsystem_type).geometry_builder
            if builder is None:
                continue
            part = builder(ledger, instance_id)
        except Exception:
            continue
        if part is None:
            continue
        ox, oy, oz = offsets[instance_id]
        for tag_name, meta in part.tags.items():
            if tag_name == "_placement" or "center" not in meta:
                continue
            center = meta["center"]
            lx, ly = center[0], center[1]
            lz = center[2] if len(center) > 2 else 0.0
            point = [lx + ox, ly + oy, lz + oz]
            features.append({
                "instance_id": instance_id,
                "tag": tag_name,
                "point": point,
                "meta": meta,
            })
    return features
