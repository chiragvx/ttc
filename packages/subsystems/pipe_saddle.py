"""Pipe Saddle -- Round trough with base + hole pattern (for clamping a tube)

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
2) -- a mounting block with an OPEN semi-circular cradle channel + two base mounting
bolts, the SAME shape family `saddle_clamp.py` already registers, reused here under this part's own
name/proportions per this catalog's established "one archetype, many named catalog entries"
convention.
"""

from __future__ import annotations

import math

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Pipe Saddle
Round trough with base + hole pattern (for clamping a tube) -- a mounting block with an OPEN semi-circular cradle channel (cradles a cylindrical
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
    """Bottom face of the saddle block (z=0, normal -Z). `_build` positions the box with
    `bd.Pos(0, 0, p.height_mm / 2.0) * bd.Box(...)`, so unlike `plate_face_interfaces`'s assumed
    ORIGIN-CENTERED box, this block's real faces sit at z=0 and z=height_mm, not +/-height_mm/2 --
    confirmed by reading `_build` directly. This is the face the two `mount[i].bore` holes pass
    through -- the real bolt-down mount against whatever structure carries the cradled tube."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _top_frame(p):
    """Top face of the saddle block (z=height_mm, normal +Z). The open cradle channel notches into
    the center of this face (at defaults, z in [height - 1.6*cradle_r, height + 0.4*cradle_r] is void
    -- confirmed against `cradle_z = height_mm - cradle_r*0.6` and `cradle_r` in `_build`), so the
    ORIGIN itself sits over open air, not solid material. This is still the real bearing PLANE a
    strap or a bridging cover plate rests on across the two flat ears on either side of the channel
    (the only material actually at z=height_mm) -- the same "spans the void, bears on the ears"
    geometry a hose clamp or zip-tie strap uses in practice, not a flush face-to-face mate."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, p.height_mm), normal=(0.0, 0.0, 1.0))


PIPE_SADDLE = register_subsystem(Subsystem(
    name="pipe_saddle",
    description="Round trough with base + hole pattern (for clamping a tube) -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm", value=25.0, min=8.0, max=100.0, unit='mm'),
        ParamSpec("width_mm", value=60.0, min=15.0, max=150.0, unit='mm'),
        ParamSpec("height_mm", value=35.0, min=8.0, max=100.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=25.0, min=5.0, max=150.0, unit='mm'),
        ParamSpec("mount_hole_dia_mm", value=4.0, min=2.0, max=10.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    fea_eligible=False,
    # 2026-07-28 (interface-coverage sweep) -- bespoke (not a shared-helper) shape: the block is
    # offset along Z (bottom at z=0, top at z=height_mm), not origin-centered like
    # `plate_face_interfaces` assumes, so its two real faces are declared directly here instead
    # (same pattern as `floor_flange.py`/`clamp_two_halves.py`, the identical-geometry sibling of
    # this file). `base` is the real bolt-down mount (the two `mount[i].bore` holes pass through it);
    # `top` is the flat ear surface beside the open cradle channel.
    interfaces=[
        InterfaceSpec(name="base", kind="mount", frame=_base_frame),
        InterfaceSpec(name="top", kind="mount", frame=_top_frame),
    ],
))
