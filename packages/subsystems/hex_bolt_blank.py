"""Hex Bolt Blank -- Hex-head bolt (unthreaded shaft) (hex flats/thread not modeled)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
1) -- a two-diameter stepped/shouldered cylinder with an optional through-bore (bore_dia_mm
near its own floor approximates a solid/blind part -- see `base.py`'s ParamSpec bounds). Fine profile
detail (hex flats, a domed/countersunk head, thread, knurl) is deliberately NOT modeled -- same
disclosed-simplification precedent `knurled_nut` already established in this catalog.
"""

from __future__ import annotations

import math

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import FitProfile

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Hex Bolt Blank
Hex-head bolt (unthreaded shaft) (hex flats/thread not modeled) -- a two-diameter stepped/shouldered cylinder, optional through-bore.
- **dia1_mm x len1_mm** -- the first (typically larger) section.
- **dia2_mm x len2_mm** -- the second section, stacked onto the first.
- **bore_dia_mm** -- concentric through-bore (set near its own floor for an effectively solid part).\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    c1 = bd.Pos(0, 0, p.len1_mm / 2.0) * bd.Cylinder(radius=p.dia1_mm / 2.0, height=p.len1_mm)
    c2 = bd.Pos(0, 0, p.len1_mm + p.len2_mm / 2.0) * bd.Cylinder(radius=p.dia2_mm / 2.0, height=p.len2_mm)
    part = c1 + c2
    part = part - bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=(p.len1_mm + p.len2_mm) * 2.0)
    return TaggedPart(part, {
        "section1.cyl": {"kind": "solid", "dia": p.dia1_mm, "height": p.len1_mm},
        "section2.cyl": {"kind": "solid", "dia": p.dia2_mm, "height": p.len2_mm},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
    })


def _volume(p) -> float:
    v1 = math.pi * (p.dia1_mm / 2.0) ** 2 * p.len1_mm
    v2 = math.pi * (p.dia2_mm / 2.0) ** 2 * p.len2_mm
    vb = math.pi * (p.bore_dia_mm / 2.0) ** 2 * (p.len1_mm + p.len2_mm)
    return max(0.0, v1 + v2 - vb)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.bore_dia_mm >= min(p.dia1_mm, p.dia2_mm):
        out.append(f"bore_dia {p.bore_dia_mm:.1f} mm >= a section diameter (no wall)")
    return out


def _head_face(p):
    """Local mate frame at section1's (the head's) bottom face -- z=0 by construction (`_build` places
    section1 from z=0 to z=len1_mm, NOT centered at the origin, unlike the generic cylinder helper).
    This is the underside of the (typically larger) head -- the face that seats flush against whatever
    the bolt bears on -- so its outward normal points -Z (away from the part)."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _tip_face(p):
    """Local mate frame at section2's (the shank's) far tip -- z = len1_mm + len2_mm by construction
    (section2 sits stacked directly on top of section1). Outward normal is +Z."""
    from packages.subsystems.base import Frame
    z = p.len1_mm + p.len2_mm
    return Frame(origin=(0.0, 0.0, z), normal=(0.0, 0.0, 1.0))


HEX_BOLT_BLANK = register_subsystem(Subsystem(
    name="hex_bolt_blank",
    description="Hex-head bolt (unthreaded shaft) -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("dia1_mm", value=10.0, min=4.0, max=30.0, unit='mm'),
        ParamSpec("dia2_mm", value=4.0, min=1.5, max=20.0, unit='mm'),
        ParamSpec("len1_mm", value=4.0, min=1.5, max=15.0, unit='mm'),
        ParamSpec("len2_mm", value=25.0, min=5.0, max=100.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=0.5, min=0.1, max=3.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # 2026-08-05 -- fit_profile HOST (see socket_cap_bolt_blank.py's own comment for the full story:
    # every bolt-blank subsystem was missing this, so a standoff/spacer could never actually derive
    # its bore from a real screw). `dia2_mm` is the shank/thread diameter; `dia1_mm` is the head.
    fit_profile=lambda p: FitProfile(kind="round", dims={"dia_mm": p.dia2_mm}),
    # 2026-07-28 (interface-coverage sweep, final wave): a stepped two-diameter shape -- section1 (the
    # head, z=0..len1_mm) with a narrower section2 (the shank) stacked on top (z=len1_mm..+len2_mm),
    # NOT centered at the origin, so `cylinder_end_interfaces` (assumes a single-diameter cylinder
    # centered at the origin) doesn't fit -- bespoke frames computed from the part's own real
    # z-offsets instead, same pattern as `button_head_bolt_blank`/`T_nut`'s flange/shaft. `head_face`
    # is the head's real bearing face; `tip_face` is the shank's free end.
    interfaces=[
        InterfaceSpec(name="head_face", kind="mount", frame=_head_face),
        InterfaceSpec(name="tip_face", kind="mount", frame=_tip_face),
    ],
))
