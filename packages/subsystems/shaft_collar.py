"""Shaft collar — a short cylinder with a bore and a radial set-screw hole."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Shaft collar
A short cylinder clamped to a shaft — axial location or thrust stop. A radial through-hole receives a
set screw (or heat-set insert) to grip the shaft.
- **outer_dia_mm** — outer diameter.
- **bore_dia_mm** — shaft bore.
- **thickness_mm** — collar length along the shaft axis.
- **set_screw_dia_mm** — radial hole for the set screw.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Cylinder(radius=p.outer_dia_mm / 2.0, height=p.thickness_mm)
    body = body - bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=p.thickness_mm * 2.0)
    # radial set-screw hole: cylinder along Y-axis at the collar centre
    screw = bd.Rot(90.0, 0.0, 0.0) * bd.Cylinder(radius=p.set_screw_dia_mm / 2.0,
                                                 height=p.outer_dia_mm * 2.0)
    body = body - screw
    return TaggedPart(body, {
        "collar.body": {"kind": "solid", "od": p.outer_dia_mm, "id": p.bore_dia_mm},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
        "set_screw.hole": {"kind": "cyl_bore", "dia": p.set_screw_dia_mm},
    })


def _volume(p):
    ro, ri = p.outer_dia_mm / 2.0, p.bore_dia_mm / 2.0
    ring = math.pi * (ro * ro - ri * ri) * p.thickness_mm
    # subtract the set-screw path (approx a straight cylinder through the ring, ignoring end-effects)
    screw = math.pi * (p.set_screw_dia_mm / 2.0) ** 2 * max(0.0, ro - ri) * 2
    return max(0.0, ring - screw)


def _check(p):
    out = []
    wall = (p.outer_dia_mm - p.bore_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        out.append(f"collar wall {wall:.2f} < min wall {_MIN_WALL_MM} mm")
    if p.set_screw_dia_mm >= wall:
        out.append(f"set-screw dia {p.set_screw_dia_mm:.1f} exceeds wall {wall:.2f}")
    return out


SHAFT_COLLAR = register_subsystem(Subsystem(
    name="shaft_collar",
    description="Shaft collar — bore + radial set screw",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("outer_dia_mm",     value=20.0, min=6.0, max=80.0, unit="mm"),
        ParamSpec("bore_dia_mm",      value=8.0,  min=2.0, max=60.0, unit="mm"),
        ParamSpec("thickness_mm",     value=10.0, min=3.0, max=40.0, unit="mm"),
        ParamSpec("set_screw_dia_mm", value=3.0,  min=1.5, max=8.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
