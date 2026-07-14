"""Washer / shim subsystem — new-style (Phase B, first migration to the ParamSpec/Subsystem model).

A flat annular ring (a spacer/shim under a fastener). Reuses `render_standoff` — a washer is an
annulus, just short. Demonstrates two subsystems sharing one primitive.
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Washer / shim
A flat annular ring (a spacer/shim under a fastener). Geometry params:
- **outer_dia_mm** — outer diameter.
- **inner_dia_mm** — bore (fastener) diameter.
- **thickness_mm** — ring thickness (the shim amount).

### Intent mapping
- "for an M5 bolt" → inner_dia_mm ≈ 5.4; "thicker shim" → increase **thickness_mm**.
- "more bearing area" → increase **outer_dia_mm** (radial wall = (outer − inner)/2 ≥ 0.8 mm).\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    from packages.truth_plane.regen.templated import render_standoff  # washer geometry ≡ short standoff
    return render_standoff(outer_dia_mm=p.outer_dia_mm, inner_dia_mm=p.inner_dia_mm, height_mm=p.thickness_mm)


def _volume(p) -> float:
    ro, ri = p.outer_dia_mm / 2.0, p.inner_dia_mm / 2.0
    return math.pi * max(0.0, ro * ro - ri * ri) * p.thickness_mm


def _check(p) -> list[str]:
    if p.inner_dia_mm >= p.outer_dia_mm:
        return [f"inner_dia {p.inner_dia_mm:.1f} mm ≥ outer_dia {p.outer_dia_mm:.1f} mm"]
    wall = (p.outer_dia_mm - p.inner_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        return [f"washer radial wall {wall:.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


WASHER = register_subsystem(Subsystem(
    name="washer",
    description="Flat annular washer/shim — FDM/FFF or stamped",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_dia_mm", value=20.0, min=6.0, max=60.0, unit="mm"),
        ParamSpec("inner_dia_mm", value=8.0,  min=2.0, max=50.0, unit="mm"),
        ParamSpec("thickness_mm", value=2.0,  min=0.8, max=10.0, unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
