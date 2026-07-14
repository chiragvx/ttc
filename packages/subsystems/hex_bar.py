"""Hex bar — extruded regular hexagonal cross-section (long structural stock)."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Hex bar
An extruded regular hexagonal bar — solid structural stock (feedstock for machining hex heads or as
wrench-shaped drive stock).
- **across_flats_mm** — key size across parallel faces.
- **length_mm** — extrusion length.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    r = p.across_flats_mm / math.sqrt(3.0)
    sketch = bd.RegularPolygon(radius=r, side_count=6)
    body = bd.extrude(sketch, amount=p.length_mm)
    return TaggedPart(body, {"bar.body": {"kind": "solid", "af": p.across_flats_mm,
                                          "length": p.length_mm}})


def _volume(p):
    hex_area = math.sqrt(3.0) / 2.0 * p.across_flats_mm ** 2
    return hex_area * p.length_mm


def _check(p):
    return []


HEX_BAR = register_subsystem(Subsystem(
    name="hex_bar",
    description="Solid hex bar — extruded hex cross-section",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("across_flats_mm", value=10.0,  min=3.0,  max=50.0,  unit="mm"),
        ParamSpec("length_mm",       value=100.0, min=10.0, max=500.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
