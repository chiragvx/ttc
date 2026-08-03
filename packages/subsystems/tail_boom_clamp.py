"""Tail Boom Clamp -- Clamp that grips the boom and bolts to the fuselage

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
1) -- a mounting block with an OPEN semi-circular cradle channel + two base mounting
bolts, the SAME shape family `saddle_clamp.py` already registers, reused here under this part's own
name/proportions per this catalog's established "one archetype, many named catalog entries"
convention.
"""

from __future__ import annotations

import math

from packages.subsystems import Frame, InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Tail Boom Clamp
Clamp that grips the boom and bolts to the fuselage -- a mounting block with an OPEN semi-circular cradle channel (cradles a cylindrical
item; not a closed ring) plus two base mounting bolts.
- **length_mm** -- clamp length along the cradled item's axis.
- **width_mm** -- overall block width, must clear the cradled diameter.
- **height_mm** -- block height.
- **bore_dia_mm** -- diameter of the item being cradled.
- **mount_hole_dia_mm** -- the two mounting-bolt clearance holes.

### Intent mapping
- "for M4 bolts" -> mount_hole_dia_mm = 4.5 (clearance); "M3" -> 3.4.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    base = bd.Pos(0, 0, p.height_mm / 2.0) * bd.Box(p.length_mm, p.width_mm, p.height_mm)
    cradle_r = p.bore_dia_mm / 2.0
    cradle_z = p.height_mm - cradle_r * 0.6
    channel = bd.Pos(0, 0, cradle_z) * (bd.Rotation(0, 90, 0) * bd.Cylinder(radius=cradle_r, height=p.length_mm * 2.0))
    part = base - channel
    tags = {
        "base.body": {"kind": "solid", "size": [p.length_mm, p.width_mm, p.height_mm]},
        "cradle.channel": {"kind": "pocket", "dia": p.bore_dia_mm},
    }
    ear_x = p.length_mm / 2.0 - p.mount_hole_dia_mm * 1.5
    ear_y = (cradle_r + p.width_mm / 2.0) / 2.0
    for i, sx in enumerate((-1, 1)):
        part = part - (bd.Pos(sx * ear_x, ear_y, 0.0) * bd.Cylinder(radius=p.mount_hole_dia_mm / 2.0, height=p.height_mm * 2.0))
        tags[f"mount[{i}].bore"] = {"kind": "cyl_bore", "center": [sx * ear_x, ear_y], "dia": p.mount_hole_dia_mm}
    return TaggedPart(part, tags)


def _volume(p) -> float:
    block_v = p.length_mm * p.width_mm * p.height_mm
    holes_v = 2 * math.pi * (p.mount_hole_dia_mm / 2.0) ** 2 * p.height_mm
    cradle_r = p.bore_dia_mm / 2.0
    cradle_v = p.length_mm * math.pi * cradle_r ** 2 * 0.85
    return max(0.0, block_v - holes_v - cradle_v)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.height_mm - p.bore_dia_mm * 0.5 < _MIN_WALL_MM:
        out.append(f"height_mm {p.height_mm:.1f} leaves no floor under a {p.bore_dia_mm:.0f}mm cradle")
    ear_margin = p.mount_hole_dia_mm + 4.0
    if p.width_mm < p.bore_dia_mm + 2 * ear_margin:
        out.append(f"width_mm {p.width_mm:.1f} doesn't leave room for mounting ears beside a "
                   f"{p.bore_dia_mm:.0f}mm cradle (need >= {p.bore_dia_mm + 2 * ear_margin:.0f})")
    if p.length_mm < p.mount_hole_dia_mm * 4.0:
        out.append(f"length_mm {p.length_mm:.1f} too short for {p.mount_hole_dia_mm:.1f}mm mounting holes")
    return out


def _base_frame(p):
    """Bottom face of the block (z=0, normal -Z). `_build` positions the box with
    `bd.Pos(0, 0, p.height_mm / 2.0) * bd.Box(...)`, so unlike `plate_face_interfaces`'s assumed
    ORIGIN-CENTERED box, this block's real faces sit at z=0 and z=height_mm, not +/-height_mm/2 --
    confirmed by reading `_build` directly. This is the face that seats flush against the fuselage --
    the two ear bolt holes pass through here, straight down from z=height_mm."""
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _top_frame(p):
    """Top face of the block (z=height_mm, normal +Z) -- where a closing strap or a second hose-clamp
    would sit to turn the open cradle into a closed ring around the boom (per the module docstring:
    this part is NOT itself a closed ring). The open cradle channel notches into the CENTER of this
    face (|y| up to ~bore_dia_mm*0.8, per `cradle_z`'s placement in `_build`), but the mounting ears at
    y=+/-ear_y stay flat all the way out to this face regardless of bore_dia_mm/height_mm, so the frame
    itself needs no bore-aware offset -- same reasoning `saddle_clamp.py` (identical base-block
    geometry) uses for its own `top` interface."""
    return Frame(origin=(0.0, 0.0, p.height_mm), normal=(0.0, 0.0, 1.0))


TAIL_BOOM_CLAMP = register_subsystem(Subsystem(
    name="tail_boom_clamp",
    description="Clamp that grips the boom and bolts to the fuselage -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm", value=25.0, min=8.0, max=100.0, unit='mm'),
        ParamSpec("width_mm", value=90.0, min=20.0, max=150.0, unit='mm'),
        ParamSpec("height_mm", value=50.0, min=10.0, max=100.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=25.0, min=5.0, max=150.0, unit='mm'),
        ParamSpec("mount_hole_dia_mm", value=4.0, min=2.0, max=10.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    fea_eligible=False,
    # 2026-07-28 (interface-coverage sweep) -- bespoke (not a shared-helper) shape: the block is offset
    # along Z (bottom at z=0, top at z=height_mm), not origin-centered like `plate_face_interfaces`
    # assumes, so its two real faces are declared directly here instead. See `_base_frame`/`_top_frame`
    # above for the geometry math -- `base` seats down against the fuselage; `top` is where a closing
    # strap would sit to turn the open cradle into a closed ring around the boom. Same archetype as
    # `saddle_clamp.py` (see this file's module docstring), same interface treatment.
    interfaces=[
        InterfaceSpec(name="base", kind="mount", frame=_base_frame),
        InterfaceSpec(name="top", kind="mount", frame=_top_frame),
    ],
))
