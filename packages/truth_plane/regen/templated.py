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

import math
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


def render_enclosure(
    *,
    width_mm: float = 80.0,
    depth_mm: float = 60.0,
    height_mm: float = 40.0,
    wall_mm: float = 2.0,
) -> TaggedPart:
    """An open-top rectangular enclosure shell: outer box minus an interior cavity (floor of thickness
    `wall_mm`, open at the top for a mating lid). Tags are generator-authored, so `shell.body` /
    `cavity.void` stay bound to design intent across regeneration."""
    outer = bd.Box(width_mm, depth_mm, height_mm)
    inner_w = width_mm - 2.0 * wall_mm
    inner_d = depth_mm - 2.0 * wall_mm
    inner_h = height_mm - wall_mm
    # over-cut 1 mm above the top face so the boolean opens the lid cleanly (no coincident faces),
    # shifted up so the cavity floor sits exactly `wall_mm` above the box bottom.
    cavity = bd.Pos(0.0, 0.0, wall_mm / 2.0 + 0.5) * bd.Box(inner_w, inner_d, inner_h + 1.0)
    part = outer - cavity
    tags: dict[str, dict] = {
        "shell.body": {"kind": "solid", "size": [width_mm, depth_mm, height_mm], "wall": wall_mm},
        "cavity.void": {"kind": "pocket", "size": [inner_w, inner_d, inner_h]},
    }
    return TaggedPart(solid=part, tags=tags)


def render_standoff(
    *,
    outer_dia_mm: float = 10.0,
    inner_dia_mm: float = 4.0,
    height_mm: float = 15.0,
) -> TaggedPart:
    """A cylindrical standoff/spacer with a concentric through-bore (a tube)."""
    body = bd.Cylinder(radius=outer_dia_mm / 2.0, height=height_mm)
    bore = bd.Cylinder(radius=inner_dia_mm / 2.0, height=height_mm * 2.0)  # over-length cut = through
    part = body - bore
    tags: dict[str, dict] = {
        "body.cyl": {"kind": "solid", "dia": outer_dia_mm, "height": height_mm},
        "bore.thru": {"kind": "cyl_bore", "dia": inner_dia_mm},
    }
    return TaggedPart(solid=part, tags=tags)


def render_lbracket(
    *,
    leg_a_mm: float = 40.0,
    leg_b_mm: float = 40.0,
    width_mm: float = 30.0,
    thickness_mm: float = 3.0,
) -> TaggedPart:
    """An L-bracket: a horizontal flange (+x) and a vertical flange (+z) sharing the corner, unioned
    into one solid. The overlapping corner box makes the union manifold."""
    t, w = thickness_mm, width_mm
    base = bd.Pos(leg_b_mm / 2.0, 0.0, t / 2.0) * bd.Box(leg_b_mm, w, t)       # x:0..leg_b, z:0..t
    wall = bd.Pos(t / 2.0, 0.0, leg_a_mm / 2.0) * bd.Box(t, w, leg_a_mm)       # x:0..t,      z:0..leg_a
    part = base + wall
    tags: dict[str, dict] = {
        "leg_b.flange": {"kind": "solid", "size": [leg_b_mm, w, t]},
        "leg_a.flange": {"kind": "solid", "size": [t, w, leg_a_mm]},
    }
    return TaggedPart(solid=part, tags=tags)


def render_uchannel(
    *,
    length_mm: float = 80.0,
    width_mm: float = 40.0,
    height_mm: float = 25.0,
    wall_mm: float = 3.0,
) -> TaggedPart:
    """An extruded U-channel: a base with two side walls, open at the top and both ends."""
    outer = bd.Box(length_mm, width_mm, height_mm)
    cav_w = width_mm - 2.0 * wall_mm
    cav_h = height_mm - wall_mm
    # cut runs through both length ends (+2) and out the top (+1) -> leaves base + two side walls
    cavity = bd.Pos(0.0, 0.0, wall_mm / 2.0 + 0.5) * bd.Box(length_mm + 2.0, cav_w, cav_h + 1.0)
    part = outer - cavity
    tags: dict[str, dict] = {
        "channel.body": {"kind": "solid", "size": [length_mm, width_mm, height_mm], "wall": wall_mm},
        "channel.void": {"kind": "pocket", "size": [length_mm, cav_w, cav_h]},
    }
    return TaggedPart(solid=part, tags=tags)


def render_panel(
    *,
    width_mm: float = 100.0,
    height_mm: float = 80.0,
    thickness_mm: float = 3.0,
    window_w_mm: float = 60.0,
    window_h_mm: float = 40.0,
    hole_dia_mm: float = 4.0,
    hole_margin_mm: float = 6.0,
) -> TaggedPart:
    """A faceplate: a flat plate with a central rectangular window and four corner mounting holes."""
    part = bd.Box(width_mm, height_mm, thickness_mm)
    part = part - bd.Box(window_w_mm, window_h_mm, thickness_mm * 2.0)
    tags: dict[str, dict] = {
        "panel.body": {"kind": "solid", "size": [width_mm, height_mm, thickness_mm]},
        "window.cut": {"kind": "pocket", "size": [window_w_mm, window_h_mm]},
    }
    off_x = width_mm / 2.0 - hole_margin_mm
    off_y = height_mm / 2.0 - hole_margin_mm
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
        part = part - (bd.Pos(sx * off_x, sy * off_y, 0.0)
                       * bd.Cylinder(radius=hole_dia_mm / 2.0, height=thickness_mm * 2.0))
        tags[f"hole[{i}].bore"] = {"kind": "cyl_bore", "center": [sx * off_x, sy * off_y], "dia": hole_dia_mm}
    return TaggedPart(solid=part, tags=tags)


def render_bulkhead_frame(
    *,
    outer_dia_mm: float = 100.0,
    inner_dia_mm: float = 80.0,
    thickness_mm: float = 3.0,
    n_bolts: int = 6,
    bolt_dia_mm: float = 4.0,
) -> TaggedPart:
    """A bulkhead ring frame: an annulus (outer minus inner diameter, `render_standoff`'s ring
    generalized) with a bolt-hole pattern evenly spaced around the flange's mid-radius — a fuselage/
    wing cross-section frame rather than a spacer."""
    body = bd.Cylinder(radius=outer_dia_mm / 2.0, height=thickness_mm)
    bore = bd.Cylinder(radius=inner_dia_mm / 2.0, height=thickness_mm * 2.0)  # over-length cut = through
    part = body - bore
    tags: dict[str, dict] = {
        "frame.body": {"kind": "solid", "dia": outer_dia_mm, "height": thickness_mm},
        "frame.bore": {"kind": "cyl_bore", "dia": inner_dia_mm},
    }
    mid_r = (outer_dia_mm + inner_dia_mm) / 4.0
    for i in range(n_bolts):
        theta = 2.0 * math.pi * i / n_bolts
        x, y = mid_r * math.cos(theta), mid_r * math.sin(theta)
        part = part - (bd.Pos(x, y, 0.0) * bd.Cylinder(radius=bolt_dia_mm / 2.0, height=thickness_mm * 2.0))
        tags[f"bolt[{i}].bore"] = {"kind": "cyl_bore", "center": [x, y], "dia": bolt_dia_mm}
    return TaggedPart(solid=part, tags=tags)


