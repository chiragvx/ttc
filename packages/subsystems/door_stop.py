"""Door Stop -- Wedge + fastener boss (fastener boss not modeled)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
2) -- a linearly-tapered wedge: a loft between two rectangular cross-sections of different
heights at each end of the length.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Door Stop
Wedge + fastener boss (fastener boss not modeled) -- a linearly-tapered wedge (FDM/FFF or CNC).
- **length_mm** -- taper direction.
- **width_mm** -- constant width.
- **height_a_mm / height_b_mm** -- thickness at each end (may be equal for an untapered plate).\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    sec_a = bd.Pos(-p.length_mm / 2.0, 0, 0) * bd.Rotation(0, 90, 0) * bd.Rectangle(p.height_a_mm, p.width_mm)
    sec_b = bd.Pos(p.length_mm / 2.0, 0, 0) * bd.Rotation(0, 90, 0) * bd.Rectangle(p.height_b_mm, p.width_mm)
    body = bd.loft([sec_a, sec_b], ruled=True)
    return TaggedPart(body, {"wedge.body": {"kind": "solid", "length": p.length_mm, "width": p.width_mm}})


def _volume(p) -> float:
    return p.length_mm * p.width_mm * (p.height_a_mm + p.height_b_mm) / 2.0


def _check(p) -> list[str]:
    if min(p.height_a_mm, p.height_b_mm) < _MIN_WALL_MM:
        return [f"thinnest end {min(p.height_a_mm, p.height_b_mm):.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


DOOR_STOP = register_subsystem(Subsystem(
    name="door_stop",
    description="Wedge + fastener boss -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm", value=40.0, min=12.0, max=120.0, unit='mm'),
        ParamSpec("width_mm", value=25.0, min=8.0, max=80.0, unit='mm'),
        ParamSpec("height_a_mm", value=25.0, min=6.0, max=80.0, unit='mm'),
        ParamSpec("height_b_mm", value=3.0, min=1.0, max=15.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
