"""Saddle clamp / P-clamp — an OPEN semi-circular cradle cut into a mounting block, for a cylindrical
item (EDF fan housing, pipe, tube) resting in the channel, plus two base-flange mounting bolts."""

from __future__ import annotations

import math

from packages.subsystems import Frame, InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Saddle clamp (P-clamp)
A rectangular mounting block with an OPEN semi-circular channel cut into its top, sized to cradle a
cylindrical item (a ducted-fan/EDF housing, a pipe, a tube). The cradled item rests in the channel and
lifts straight out — this is NOT a closed ring; a strap or a second hose-clamp over the top closes it
if needed. Two vertical bolt holes through the base flange (one near each end) mount the clamp down.
- **length_mm** — clamp length along the cradled item's axis.
- **width_mm** — overall block width, must clear the cradled diameter.
- **height_mm** — block height, base to the top of the un-cut block.
- **bore_dia_mm** — diameter of the item being cradled.
- **mount_hole_dia_mm** — the two mounting-bolt clearance holes.

### Intent mapping
- "70mm EDF" / "70mm fan housing" -> bore_dia_mm ~= 70.
- "M4 bolts" / "M4 mounting" -> mount_hole_dia_mm = 4.5 (clearance); "M3" -> 3.4.
- "cradle a 1-inch pipe" -> bore_dia_mm ~= 25.4.\
"""

_MIN_WALL_MM = 0.8  # FDM min-wall floor, packages/ledger/apply.py::MIN_WALL_MM


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart

    base = bd.Pos(0, 0, p.height_mm / 2.0) * bd.Box(p.length_mm, p.width_mm, p.height_mm)

    cradle_r = p.bore_dia_mm / 2.0
    # Center the cradle cylinder near the top so ~60% of its radius pokes out above the block's top
    # face (z=height_mm) — this leaves the channel OPEN rather than a fully-embedded closed bore.
    cradle_z = p.height_mm - cradle_r * 0.6
    # Cylinder defaults to a Z axis; rotate 90 deg about Y to swing it onto the X axis (channel runs
    # the length of the block). Over-length (2x) so it cuts fully through along X regardless of
    # length_mm — same over-cut pattern render_enclosure uses for its cavity cut.
    channel = bd.Pos(0, 0, cradle_z) * (bd.Rotation(0, 90, 0) * bd.Cylinder(radius=cradle_r, height=p.length_mm * 2.0))
    part = base - channel

    tags = {
        "base.body": {"kind": "solid", "size": [p.length_mm, p.width_mm, p.height_mm]},
        "cradle.channel": {"kind": "pocket", "dia": p.bore_dia_mm},
    }
    # Mounting holes go through the solid EAR material to the side of the channel (y offset toward
    # the block's edges), not at y=0 under the channel — dead-center the channel has already removed
    # everything above the thin base floor, so a y=0 hole would barely pass through any real material.
    # The channel never reaches beyond |y| = cradle_r regardless of z, so centering the ear halfway
    # between the channel's edge and the block's outer edge keeps it clear of the cut at any width.
    ear_x = p.length_mm / 2.0 - p.mount_hole_dia_mm * 1.5
    ear_y = (cradle_r + p.width_mm / 2.0) / 2.0
    for i, sx in enumerate((-1, 1)):
        part = part - (bd.Pos(sx * ear_x, ear_y, 0.0) * bd.Cylinder(radius=p.mount_hole_dia_mm / 2.0, height=p.height_mm * 2.0))
        tags[f"mount[{i}].bore"] = {"kind": "cyl_bore", "center": [sx * ear_x, ear_y], "dia": p.mount_hole_dia_mm}

    return TaggedPart(part, tags)


def _volume(p):
    block_v = p.length_mm * p.width_mm * p.height_mm
    holes_v = 2 * math.pi * (p.mount_hole_dia_mm / 2.0) ** 2 * p.height_mm
    cradle_r = p.bore_dia_mm / 2.0
    # Approximation: most of the cradle circle is embedded in the block and only a small top sliver
    # is exposed/open, so we estimate the cut volume as ~85% of the full circular cross-section swept
    # the length of the block (not exact — the true removed volume depends on the channel/top-face
    # intersection geometry, which is a good deal cheaper to approximate than to integrate here).
    cradle_v = p.length_mm * math.pi * cradle_r ** 2 * 0.85
    return max(0.0, block_v - holes_v - cradle_v)


def _check(p):
    out = []
    if p.height_mm - p.bore_dia_mm * 0.5 < _MIN_WALL_MM:
        out.append(f"height_mm {p.height_mm:.1f} leaves no floor under a {p.bore_dia_mm:.0f}mm cradle")
    # width must clear the bore AND leave room for a real mounting ear (hole dia + wall margin) on
    # each side — not just a few mm of clearance around the bore itself.
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
    confirmed by reading `_build` directly. This is the face that seats flush against a mounting
    surface -- the two ear bolt holes pass through here, straight down from z=height_mm."""
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _top_frame(p):
    """Top face of the block (z=height_mm, normal +Z) -- where a closing strap or a second hose-clamp
    would sit if the open cradle needs to become a closed ring (per the module docstring: this part is
    NOT itself a closed ring). The open cradle channel notches into the CENTER of this face (|y| up to
    ~bore_dia_mm*0.8, per `cradle_z`'s placement in `_build`), but the mounting ears at y=+/-ear_y stay
    flat all the way out to this face regardless of bore_dia_mm/height_mm, so the frame itself needs no
    bore-aware offset -- same reasoning `clamp_two_halves.py` (identical base-block geometry) uses for
    its own `top` interface."""
    return Frame(origin=(0.0, 0.0, p.height_mm), normal=(0.0, 0.0, 1.0))


SADDLE_CLAMP = register_subsystem(Subsystem(
    name="saddle_clamp",
    description="Open semi-circular saddle/P-clamp — cradles a cylindrical item (fan housing, pipe, tube) with two mounting bolts",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",          value=20.0, min=8.0,  max=100.0, unit="mm"),
        ParamSpec("width_mm",           value=110.0, min=15.0, max=150.0, unit="mm"),
        ParamSpec("height_mm",          value=60.0, min=10.0, max=100.0, unit="mm"),
        ParamSpec("bore_dia_mm",        value=70.0, min=5.0,  max=200.0, unit="mm"),
        ParamSpec("mount_hole_dia_mm",  value=4.5,  min=2.0,  max=12.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    # DELIBERATE: the cradle channel cuts through both X ends, so this part's cross-section isn't a
    # single-face-per-X-end box — it does not qualify for the validated cantilever FS methodology.
    # FS honestly stays "unknown" for this part type. See base.py's fea_eligible docstring.
    fea_eligible=False,
    # 2026-07-28 (interface-coverage sweep) -- bespoke (not a shared-helper) shape: the block is offset
    # along Z (bottom at z=0, top at z=height_mm), not origin-centered like `plate_face_interfaces`
    # assumes, so its two real faces are declared directly here instead. See `_base_frame`/`_top_frame`
    # above for the geometry math -- `base` seats down against a mount surface; `top` is where a
    # closing strap would sit to turn the open cradle into a closed ring.
    interfaces=[
        InterfaceSpec(name="base", kind="mount", frame=_base_frame),
        InterfaceSpec(name="top", kind="mount", frame=_top_frame),
    ],
))
