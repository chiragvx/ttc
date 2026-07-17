"""Flat Head Bolt Blank -- Countersunk head + shank (countersink taper/thread not modeled, approximated as a flat head)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
1) -- a two-diameter stepped/shouldered cylinder with an optional through-bore (bore_dia_mm
near its own floor approximates a solid/blind part -- see `base.py`'s ParamSpec bounds). Fine profile
detail (hex flats, a domed/countersunk head, thread, knurl) is deliberately NOT modeled -- same
disclosed-simplification precedent `knurled_nut` already established in this catalog.
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Flat Head Bolt Blank
Countersunk head + shank (countersink taper/thread not modeled, approximated as a flat head) -- a two-diameter stepped/shouldered cylinder, optional through-bore.
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


FLAT_HEAD_BOLT_BLANK = register_subsystem(Subsystem(
    name="flat_head_bolt_blank",
    description="Countersunk head + shank -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("dia1_mm", value=10.0, min=4.0, max=28.0, unit='mm'),
        ParamSpec("dia2_mm", value=4.0, min=1.5, max=18.0, unit='mm'),
        ParamSpec("len1_mm", value=2.5, min=1.0, max=8.0, unit='mm'),
        ParamSpec("len2_mm", value=20.0, min=5.0, max=80.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=0.5, min=0.1, max=3.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
