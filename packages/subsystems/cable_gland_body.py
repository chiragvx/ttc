"""Cable Gland Body -- Cylindrical gland with strain relief (strain-relief ribs/thread not modeled)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
10) -- a two-diameter stepped/shouldered cylinder with an optional through-bore (bore_dia_mm
near its own floor approximates a solid/blind part -- see `base.py`'s ParamSpec bounds). Fine profile
detail (hex flats, a domed/countersunk head, thread, knurl) is deliberately NOT modeled -- same
disclosed-simplification precedent `knurled_nut` already established in this catalog.
"""

from __future__ import annotations

import math

from packages.subsystems import Frame, InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Cable Gland Body
Cylindrical gland with strain relief (strain-relief ribs/thread not modeled) -- a two-diameter stepped/shouldered cylinder, optional through-bore.
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


def _base_face(p) -> Frame:
    """The z=0 end of section1 (the first, typically-larger-diameter section, per `_build`'s
    `c1 = Pos(0, 0, len1/2) * Cylinder(dia1/2, len1)`) -- the part is NOT centered at the origin like
    `cylinder_end_interfaces` assumes (it stacks upward from z=0), so that generic helper doesn't fit;
    this bespoke pair computes the real end z's instead. `normal` points OUTWARD (-Z), away from the
    stack, matching `Frame`'s anti-parallel-touching-normals mating convention."""
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _tip_face(p) -> Frame:
    """The far end of section2 (the second, typically-smaller-diameter/cable-exit section), at
    z = len1_mm + len2_mm per `_build`'s stacking. `normal` points OUTWARD (+Z)."""
    return Frame(origin=(0.0, 0.0, p.len1_mm + p.len2_mm), normal=(0.0, 0.0, 1.0))


CABLE_GLAND_BODY = register_subsystem(Subsystem(
    name="cable_gland_body",
    description="Cylindrical gland with strain relief -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("dia1_mm", value=14.0, min=5.0, max=45.0, unit='mm'),
        ParamSpec("dia2_mm", value=10.0, min=3.0, max=35.0, unit='mm'),
        ParamSpec("len1_mm", value=8.0, min=2.0, max=25.0, unit='mm'),
        ParamSpec("len2_mm", value=15.0, min=4.0, max=45.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=5.0, min=1.5, max=25.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # 2026-07-28 -- bespoke, not `cylinder_end_interfaces`: the stacked-cylinder solid spans z in
    # [0, len1_mm+len2_mm], NOT centered at the origin the generic helper assumes. Two real end faces:
    # the section1 (larger) base and the section2 (smaller) tip.
    interfaces=[
        InterfaceSpec(name="base_face", kind="mount", frame=_base_face),
        InterfaceSpec(name="tip_face", kind="mount", frame=_tip_face),
    ],
))
