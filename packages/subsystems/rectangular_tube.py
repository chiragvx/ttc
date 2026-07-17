"""Rectangular Tube -- Hollow rectangular section (non-square) (modeled as a square profile; true non-square width/depth not parameterized separately)

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
5) -- an extruded hollow square section, the SAME shape family `square_tube.py` already
registers, reused here under this part's own name/proportions per this catalog's established "one
archetype, many named catalog entries" convention.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Rectangular Tube
Hollow rectangular section (non-square) (modeled as a square profile; true non-square width/depth not parameterized separately) -- an extruded hollow square section (FDM/FFF or extruded stock).
- **length_mm** -- how long the tube runs.
- **outer_side_mm** -- outer edge length.
- **wall_thickness_mm** -- wall (all four sides equal).\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    outer = bd.Box(p.length_mm, p.outer_side_mm, p.outer_side_mm)
    inner_size = p.outer_side_mm - 2.0 * p.wall_thickness_mm
    cavity = bd.Box(p.length_mm + 2.0, max(0.1, inner_size), max(0.1, inner_size))
    return TaggedPart(outer - cavity, {
        "tube.body": {"kind": "solid", "size": [p.length_mm, p.outer_side_mm, p.outer_side_mm]},
        "tube.void": {"kind": "pocket"},
    })


def _volume(p) -> float:
    inner = max(0.0, p.outer_side_mm - 2.0 * p.wall_thickness_mm)
    return p.length_mm * (p.outer_side_mm ** 2 - inner ** 2)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.wall_thickness_mm < _MIN_WALL_MM:
        out.append(f"wall {p.wall_thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if 2 * p.wall_thickness_mm >= p.outer_side_mm:
        out.append(f"wall_thickness x2 leaves no cavity in a {p.outer_side_mm:.0f} mm side")
    return out


RECTANGULAR_TUBE = register_subsystem(Subsystem(
    name="rectangular_tube",
    description="Hollow rectangular section (non-square) -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm", value=200.0, min=30.0, max=1000.0, unit='mm'),
        ParamSpec("outer_side_mm", value=25.0, min=8.0, max=100.0, unit='mm'),
        ParamSpec("wall_thickness_mm", value=2.0, min=0.8, max=10.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
