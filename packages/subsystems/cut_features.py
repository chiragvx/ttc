"""Generic cut-feature primitive (hole / pocket / slot) — usable on ANY subsystem instance's
geometry, with zero per-subsystem hardcoding. Mirrors the boolean-subtract idiom already validated
in `packages/truth_plane/regen/templated.py::render_panel` (see module docstring there), but derives
the cut's Z-origin from the HOST's own current bounding box instead of a hardcoded per-subsystem
"thickness_mm" param — so it composes with box, cylinder, or compound hosts alike.

Pure orchestration: `swept_volume_mm3` / `host_bounding_box_mm` are plain arithmetic (no OCCT).
`apply_cut_features` imports build123d LAZILY inside the function body (matching this package's
established convention, see e.g. `flat_bar.py::_build`) — importing this module must never drag in
the kernel for pure-Python callers (schema validation, the analytic `_volume` path, tests without
build123d installed).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.ledger.schema import CutFeature
    from packages.truth_plane.regen.templated import TaggedPart

# A tiny OCCT-robustness margin ADDED TO THE CUTTER ONLY (never to `feature.depth_mm`, never stored
# in the ledger, never seen by `swept_volume_mm3`'s analytic accounting). A "through" cut's declared
# depth is the host's TRUE Z-extent (see packages/ledger/apply.py's `through` resolution) -- so its
# cutter's bottom face would otherwise land EXACTLY on the host's own bottom face, a coincident
# boundary that can leave a razor-thin unremoved sliver (or a fragile/degenerate boolean) under
# floating-point rounding. Extending the cutter a hair further, without touching the reported depth,
# keeps `depth_mm` an honest, ungrounded-free fact while keeping the actual cut robust.
OVERHANG_MM = 0.5


def swept_volume_mm3(feature: "CutFeature") -> float:
    """Pure-arithmetic swept volume of one cut feature (no OCCT) — the fast analytic path used by
    `register_subsystem`'s `_volume` closure, which must never need a geometry build."""
    if feature.shape == "circle":
        return math.pi * (feature.dia_mm / 2.0) ** 2 * feature.depth_mm
    return feature.length_mm * feature.width_mm * feature.depth_mm


def host_bounding_box_mm(part: "TaggedPart") -> tuple[float, float, float]:
    """(size.X, size.Y, size.Z) of `part`'s CURRENT built solid. Used by a later stage (not this one)
    to resolve a conversational "through" depth to a concrete number and to validate a proposed
    feature's fit before it is ever added to the ledger — built now so that later stage doesn't have
    to re-derive the bounding-box pattern."""
    bbox = part.solid.bounding_box()
    return (float(bbox.size.X), float(bbox.size.Y), float(bbox.size.Z))


def apply_cut_features(part: "TaggedPart", features: list["CutFeature"]) -> "TaggedPart":
    """Subtract each of `features` from `part`'s solid, one at a time, in host-local XY, each cut
    originating from the HOST's own top face (its current bounding box's `max.Z`) and running down
    `depth_mm`. Cheap no-op — returns `part` unchanged — when `features` is empty, so this adds zero
    overhead on the (overwhelmingly common) build of a part with no cuts.

    Tags are ADDED (never namespaced/rewritten) as `cut[<feature.id>].feature`, so this composes
    transparently with whatever tagging convention the host subsystem already uses.

    Raises `ValueError` if the cut(s) sever the part into anything other than exactly one connected
    solid (a real fabrication error, not something to silently paper over) — left to propagate; the
    existing defensive per-instance callers (`render_assembly`, mesh, export) already catch exceptions
    and skip/report per instance.
    """
    if not features:
        return part

    import build123d as bd

    from packages.truth_plane.regen.templated import TaggedPart

    bbox = part.solid.bounding_box()
    top_z = bbox.max.Z
    solid = part.solid
    tags = dict(part.tags)
    for feature in features:
        depth = feature.depth_mm
        # cutter height gets the small OCCT-robustness overhang (see OVERHANG_MM above); the TOP face
        # stays pinned exactly at `top_z` (the cut still originates at the host's own top face, per
        # this function's contract) -- only the bottom face is pushed further down, into whatever is
        # there (more host material for a partial-depth pocket -- removes nothing extra beyond
        # `depth` since the boolean only removes what's actually solid; empty space for a full
        # through-penetration -- removes nothing at all there either).
        cutter_height = depth + OVERHANG_MM
        z_center = top_z - depth / 2.0 - OVERHANG_MM / 2.0
        if feature.shape == "circle":
            cutter = bd.Cylinder(radius=feature.dia_mm / 2.0, height=cutter_height)
        else:
            cutter = bd.Box(feature.length_mm, feature.width_mm, cutter_height)
        cutter = bd.Pos(feature.x_mm, feature.y_mm, z_center) * cutter
        solid = solid - cutter
        tags[f"cut[{feature.id}].feature"] = {
            "kind": feature.kind,
            "shape": feature.shape,
            "center": [feature.x_mm, feature.y_mm],
            "dia": feature.dia_mm,
            "length": feature.length_mm,
            "width": feature.width_mm,
            "depth": feature.depth_mm,
        }

    result = TaggedPart(solid=solid, tags=tags)
    n_solids = len(result.solid.solids())
    if n_solids != 1:
        raise ValueError(
            f"cut feature(s) severed the part into {n_solids} disconnected islands (expected 1)"
        )
    return result
