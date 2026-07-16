"""Snap Pin -- Simple snap pin for a removable joint

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
13) -- a cylinder with a concentric through-bore, the SAME shape family `standoff.py`
already registers (`render_standoff`), reused here under this part's own name/proportions per this
catalog's established "one archetype, many named catalog entries" convention (see `standoff.py`/
`washer.py`: washer already reuses the standoff generator the same way).
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Snap Pin
Simple snap pin for a removable joint -- a cylindrical body with a concentric through-bore (FDM/FFF or turned).
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


SNAP_PIN = register_subsystem(Subsystem(
    name="snap_pin",
    description="Simple snap pin for a removable joint -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_dia_mm", value=4.0, min=2.0, max=15.0, unit='mm'),
        ParamSpec("inner_dia_mm", value=1.0, min=0.1, max=8.0, unit='mm'),
        ParamSpec("height_mm", value=20.0, min=5.0, max=70.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
