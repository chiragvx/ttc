"""Templated, tag-baked geometry generation — Spike 1 fallback #1 (generator-deterministic tags).

The topological-naming problem (positional OCCT sub-shape ids renumber on regen) is sidestepped for
features the GENERATOR creates: because the templater knows what it made, it emits a stable, semantic
tag map (`hole[2].bore` -> its design intent) that survives regeneration and parameter changes.

Honest scope: this gives a stable tag -> *intent* map (enough for regen, optimizer feature-targeting,
and parametric edits). Mapping a tag back to the exact OCCT face in the booleaned result (for picking
/ HUD anchoring) still needs the geometric-signature backstop or OCAF — Spike 1's remaining work,
owned by the OCCT engineer. This module deliberately does the part that does NOT need them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import build123d as bd


@dataclass
class TaggedPart:
    solid: object
    tags: dict[str, dict] = field(default_factory=dict)

    @property
    def tag_keys(self) -> set[str]:
        return set(self.tags)


def _hole_centers(width: float, n: int, margin: float) -> list[float]:
    if n <= 1:
        return [0.0]
    span = width - 2 * margin
    step = span / (n - 1)
    start = -span / 2
    return [start + i * step for i in range(n)]


def render_bracket(
    *,
    width_mm: float = 60.0,
    depth_mm: float = 40.0,
    thickness_mm: float = 5.0,
    hole_dia_mm: float = 6.0,
    n_holes: int = 4,
    margin_mm: float = 8.0,
) -> TaggedPart:
    """A mounting bracket: a plate with a row of bolt holes. Returns the solid + a baked tag map.

    The booleans here (hole cuts) are exactly the face-splitting case that breaks positional identity
    — but the tags are generator-authored, so `hole[i]` stays bound to design intent regardless of how
    OCCT renumbers faces."""
    part = bd.Box(width_mm, depth_mm, thickness_mm)
    tags: dict[str, dict] = {
        "plate.body": {"kind": "solid", "size": [width_mm, depth_mm, thickness_mm]},
    }
    for i, cx in enumerate(_hole_centers(width_mm, n_holes, margin_mm)):
        part = part - (bd.Pos(cx, 0.0, 0.0) * bd.Cylinder(radius=hole_dia_mm / 2.0, height=thickness_mm * 2.0))
        tags[f"hole[{i}].bore"] = {"kind": "cyl_bore", "center": [cx, 0.0], "dia": hole_dia_mm}
    return TaggedPart(solid=part, tags=tags)
