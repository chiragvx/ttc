"""Hex nut — regular hexagonal prism with a through-bore."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Hex nut
A regular hexagonal nut — thread is not modeled; the bore is the tapped-drill diameter (a heat-set
insert or tap is added downstream). Parametric across-flats key size.
- **across_flats_mm** — wrench size (e.g. 10 mm ≈ M6 nut).
- **thickness_mm** — nut height.
- **bore_dia_mm** — through-hole (tap drill or clearance).\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    r = p.across_flats_mm / math.sqrt(3.0)  # circumradius from across-flats
    sketch = bd.RegularPolygon(radius=r, side_count=6)
    body = bd.extrude(sketch, amount=p.thickness_mm)
    body = body - bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=p.thickness_mm * 2.0)
    return TaggedPart(body, {
        "nut.body": {"kind": "solid", "af": p.across_flats_mm, "h": p.thickness_mm},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
    })


def _volume(p):
    hex_area = math.sqrt(3.0) / 2.0 * p.across_flats_mm ** 2
    bore_area = math.pi * (p.bore_dia_mm / 2.0) ** 2
    return max(0.0, (hex_area - bore_area) * p.thickness_mm)


def _check(p):
    out = []
    wall = (p.across_flats_mm - p.bore_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        out.append(f"nut wall {wall:.2f} < min wall {_MIN_WALL_MM} mm")
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} < min wall {_MIN_WALL_MM} mm")
    return out


HEX_NUT = register_subsystem(Subsystem(
    name="hex_nut",
    description="Hex nut — hex prism with through-bore",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("across_flats_mm", value=10.0, min=4.0, max=50.0, unit="mm"),
        ParamSpec("thickness_mm",    value=5.0,  min=1.0, max=30.0, unit="mm"),
        ParamSpec("bore_dia_mm",     value=6.0,  min=2.0, max=45.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
