"""Linear Bearing Block -- Rectangular slider block with a bore

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
8) -- a flat plate with a central round bore (a shaft/spindle clearance) plus four corner
mounting holes -- the SAME shape family `panel.py` already registers, with a round center bore instead
of a rectangular window.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Linear Bearing Block
Rectangular slider block with a bore -- a flat plate with a central round bore and four corner mounting holes.
- **width_mm x depth_mm** -- plate footprint.
- **thickness_mm** -- plate thickness.
- **bore_dia_mm** -- central round bore/clearance.
- **hole_dia_mm x hole_margin_mm** -- four corner mounting holes.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    part = bd.Box(p.width_mm, p.depth_mm, p.thickness_mm)
    part = part - bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=p.thickness_mm * 2.0)
    tags = {
        "plate.body": {"kind": "solid", "size": [p.width_mm, p.depth_mm, p.thickness_mm]},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
    }
    off_x, off_y = p.width_mm / 2.0 - p.hole_margin_mm, p.depth_mm / 2.0 - p.hole_margin_mm
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
        part = part - (bd.Pos(sx * off_x, sy * off_y, 0.0) * bd.Cylinder(radius=p.hole_dia_mm / 2.0, height=p.thickness_mm * 2.0))
        tags[f"hole[{i}].bore"] = {"kind": "cyl_bore", "center": [sx * off_x, sy * off_y], "dia": p.hole_dia_mm}
    return TaggedPart(part, tags)


def _volume(p) -> float:
    import math
    plate_v = p.width_mm * p.depth_mm * p.thickness_mm
    bore_v = math.pi * (p.bore_dia_mm / 2.0) ** 2 * p.thickness_mm
    holes_v = 4 * math.pi * (p.hole_dia_mm / 2.0) ** 2 * p.thickness_mm
    return max(0.0, plate_v - bore_v - holes_v)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.bore_dia_mm >= min(p.width_mm, p.depth_mm):
        out.append(f"bore_dia {p.bore_dia_mm:.1f} mm too large for the plate")
    return out


LINEAR_BEARING_BLOCK = register_subsystem(Subsystem(
    name="linear_bearing_block",
    description="Rectangular slider block with a bore -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("width_mm", value=30.0, min=10.0, max=90.0, unit='mm'),
        ParamSpec("depth_mm", value=25.0, min=8.0, max=80.0, unit='mm'),
        ParamSpec("thickness_mm", value=20.0, min=6.0, max=60.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=12.0, min=3.0, max=50.0, unit='mm'),
        ParamSpec("hole_dia_mm", value=3.4, min=1.5, max=8.0, unit='mm'),
        ParamSpec("hole_margin_mm", value=5.0, min=2.0, max=15.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
