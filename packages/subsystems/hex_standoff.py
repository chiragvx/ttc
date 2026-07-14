"""Hex standoff — hex outer profile with a through-bore (tool-grippable spacer)."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Hex standoff
Like a standoff (cylindrical spacer with a through-bore), but with a hex outer profile so a wrench
can grip it during assembly.
- **across_flats_mm** — outer key size.
- **bore_dia_mm** — through-bore.
- **length_mm** — standoff distance along the fastener axis.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    r = p.across_flats_mm / math.sqrt(3.0)
    sketch = bd.RegularPolygon(radius=r, side_count=6)
    body = bd.extrude(sketch, amount=p.length_mm)
    body = body - bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=p.length_mm * 2.0)
    return TaggedPart(body, {
        "standoff.body": {"kind": "solid", "af": p.across_flats_mm, "length": p.length_mm},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
    })


def _volume(p):
    hex_area = math.sqrt(3.0) / 2.0 * p.across_flats_mm ** 2
    bore_area = math.pi * (p.bore_dia_mm / 2.0) ** 2
    return max(0.0, (hex_area - bore_area) * p.length_mm)


def _check(p):
    out = []
    wall = (p.across_flats_mm - p.bore_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        out.append(f"standoff wall {wall:.2f} < min wall {_MIN_WALL_MM} mm")
    return out


HEX_STANDOFF = register_subsystem(Subsystem(
    name="hex_standoff",
    description="Hex-profile standoff/spacer with through-bore",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("across_flats_mm", value=6.0,  min=3.0, max=30.0, unit="mm"),
        ParamSpec("bore_dia_mm",     value=3.0,  min=1.0, max=25.0, unit="mm"),
        ParamSpec("length_mm",       value=20.0, min=3.0, max=80.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
