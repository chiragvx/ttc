"""Jack Point -- Reinforced point for a ground jack

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
4) -- a cylinder with a concentric through-bore, the SAME shape family `standoff.py`
already registers (`render_standoff`), reused here under this part's own name/proportions per this
catalog's established "one archetype, many named catalog entries" convention (see `standoff.py`/
`washer.py`: washer already reuses the standoff generator the same way).
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Jack Point
Reinforced point for a ground jack -- a cylindrical body with a concentric through-bore (FDM/FFF or turned).
- **outer_dia_mm** -- outer diameter.
- **inner_dia_mm** -- bore diameter.
- **height_mm** -- length along the axis.

### Intent mapping
- "for an M3 screw" -> inner_dia_mm ~= 3.4 (clearance); "M4" -> 4.5.
- "taller" / "longer" -> increase height_mm.
- "thicker wall" / "stronger" -> increase outer_dia_mm (wall = (outer - inner)/2, >= 0.8 mm).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_standoff
    return render_standoff(outer_dia_mm=p.outer_dia_mm, inner_dia_mm=p.inner_dia_mm, height_mm=p.height_mm)


def _volume(p) -> float:
    ro, ri = p.outer_dia_mm / 2.0, p.inner_dia_mm / 2.0
    return math.pi * max(0.0, ro * ro - ri * ri) * p.height_mm


def _check(p) -> list[str]:
    if p.inner_dia_mm >= p.outer_dia_mm:
        return [f"inner_dia {p.inner_dia_mm:.1f} mm >= outer_dia {p.outer_dia_mm:.1f} mm (no wall)"]
    wall = (p.outer_dia_mm - p.inner_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        return [f"wall {wall:.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


JACK_POINT = register_subsystem(Subsystem(
    name="jack_point",
    description="Reinforced point for a ground jack -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_dia_mm", value=14.0, min=5.0, max=50.0, unit='mm'),
        ParamSpec("inner_dia_mm", value=5.0, min=1.0, max=30.0, unit='mm'),
        ParamSpec("height_mm", value=15.0, min=3.0, max=60.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
