"""Standoff / spacer subsystem — a cylinder with a concentric through-bore."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Standoff / spacer
A cylindrical spacer with a concentric through-bore (a tube). Geometry params:
- **outer_dia_mm** — outer diameter.
- **inner_dia_mm** — bore diameter (clearance for the fastener passing through).
- **height_mm** — length along the axis (the standoff distance).

### Intent mapping
- "for an M3 screw" → inner_dia_mm ≈ 3.4 (clearance); "M4" → 4.5.
- "taller"/"more spacing" → increase **height_mm**.
- "thicker wall"/"stronger" → increase **outer_dia_mm** (wall = (outer − inner)/2, ≥ 0.8 mm).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_standoff
    return render_standoff(outer_dia_mm=p.outer_dia_mm, inner_dia_mm=p.inner_dia_mm, height_mm=p.height_mm)


def _volume(p) -> float:
    ro, ri = p.outer_dia_mm / 2.0, p.inner_dia_mm / 2.0
    return math.pi * max(0.0, ro * ro - ri * ri) * p.height_mm


def _check(p) -> list[str]:
    if p.inner_dia_mm >= p.outer_dia_mm:
        return [f"inner_dia {p.inner_dia_mm:.1f} mm ≥ outer_dia {p.outer_dia_mm:.1f} mm (no wall)"]
    wall = (p.outer_dia_mm - p.inner_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        return [f"standoff wall {wall:.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


STANDOFF = register_subsystem(Subsystem(
    name="standoff",
    description="Cylindrical standoff/spacer with a through-bore — FDM/FFF or turned",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_dia_mm", value=10.0, min=4.0, max=40.0, unit="mm"),
        ParamSpec("inner_dia_mm", value=4.0,  min=1.0, max=30.0, unit="mm"),
        ParamSpec("height_mm",    value=15.0, min=2.0, max=60.0, unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
