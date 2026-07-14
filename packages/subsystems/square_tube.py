"""Square tube — hollow square section (outer box minus inner box, open both ends)."""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Square tube
An extruded hollow square section — a light, stiff structural member.
- **length_mm** — how long the tube runs.
- **outer_side_mm** — outer edge length.
- **wall_thickness_mm** — wall (all four sides equal).\
"""

_MIN_WALL_MM = 0.8


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


def _volume(p):
    inner = max(0.0, p.outer_side_mm - 2.0 * p.wall_thickness_mm)
    return p.length_mm * (p.outer_side_mm**2 - inner**2)


def _check(p):
    out = []
    if p.wall_thickness_mm < _MIN_WALL_MM:
        out.append(f"wall {p.wall_thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if 2 * p.wall_thickness_mm >= p.outer_side_mm:
        out.append(f"wall_thickness ×2 leaves no cavity in a {p.outer_side_mm:.0f} mm side")
    return out


SQUARE_TUBE = register_subsystem(Subsystem(
    name="square_tube",
    description="Extruded hollow square tube — structural section",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",         value=100.0, min=20.0, max=500.0, unit="mm"),
        ParamSpec("outer_side_mm",     value=20.0,  min=6.0,  max=100.0, unit="mm"),
        ParamSpec("wall_thickness_mm", value=2.0,   min=0.8,  max=10.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
