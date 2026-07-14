"""Cover plate — flat rectangular plate with a central through-bore (e.g. electrical box cover)."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Cover plate
A flat rectangular plate with a single central through-bore (electrical box covers, cable pass-throughs).
- **width_mm × height_mm × thickness_mm** — plate outline.
- **bore_dia_mm** — the central bore.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    plate = bd.Box(p.width_mm, p.height_mm, p.thickness_mm)
    bore = bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=p.thickness_mm * 2.0)
    return TaggedPart(plate - bore, {
        "plate.body": {"kind": "solid", "size": [p.width_mm, p.height_mm, p.thickness_mm]},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
    })


def _volume(p):
    return p.width_mm * p.height_mm * p.thickness_mm - math.pi * (p.bore_dia_mm / 2.0) ** 2 * p.thickness_mm


def _check(p):
    out = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.bore_dia_mm >= min(p.width_mm, p.height_mm) - 2 * _MIN_WALL_MM:
        out.append(f"bore_dia {p.bore_dia_mm:.1f} leaves no frame — reduce or grow the plate")
    return out


COVER_PLATE = register_subsystem(Subsystem(
    name="cover_plate",
    description="Flat plate with a central through-bore — cover / pass-through",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("width_mm",     value=60.0, min=20.0, max=250.0, unit="mm"),
        ParamSpec("height_mm",    value=40.0, min=20.0, max=250.0, unit="mm"),
        ParamSpec("thickness_mm", value=3.0,  min=0.8,  max=10.0,  unit="mm"),
        ParamSpec("bore_dia_mm",  value=15.0, min=2.0,  max=100.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    fea_eligible=True,  # single Box minus a central bore, span along X — same validated methodology
))
