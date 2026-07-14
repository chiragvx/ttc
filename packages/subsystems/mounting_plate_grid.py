"""Mounting-plate grid — a plate with an N×M grid of through-holes."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Mounting-plate grid
A flat plate with a regular grid of through-holes — versatile chassis mounting surface.
- **width_mm × height_mm × thickness_mm** — plate outline.
- **cols × rows** — grid dimensions (integer counts).
- **hole_dia_mm** — through-hole diameter (each hole in the grid identical).
- **hole_spacing_mm** — pitch between hole centres (equal in X and Y).\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    plate = bd.Box(p.width_mm, p.height_mm, p.thickness_mm)
    cols, rows = int(round(p.cols)), int(round(p.rows))
    tags = {"plate.body": {"kind": "solid", "size": [p.width_mm, p.height_mm, p.thickness_mm]}}
    span_x = (cols - 1) * p.hole_spacing_mm
    span_y = (rows - 1) * p.hole_spacing_mm
    for i in range(cols):
        for j in range(rows):
            x = -span_x / 2.0 + i * p.hole_spacing_mm
            y = -span_y / 2.0 + j * p.hole_spacing_mm
            plate = plate - (bd.Pos(x, y, 0.0) * bd.Cylinder(radius=p.hole_dia_mm / 2.0,
                                                             height=p.thickness_mm * 2.0))
            tags[f"hole[{i},{j}].bore"] = {"kind": "cyl_bore", "center": [x, y], "dia": p.hole_dia_mm}
    return TaggedPart(plate, tags)


def _volume(p):
    cols, rows = int(round(p.cols)), int(round(p.rows))
    hole_v = math.pi * (p.hole_dia_mm / 2.0) ** 2 * p.thickness_mm
    return p.width_mm * p.height_mm * p.thickness_mm - cols * rows * hole_v


def _check(p):
    out = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    cols, rows = int(round(p.cols)), int(round(p.rows))
    span_x = (cols - 1) * p.hole_spacing_mm + p.hole_dia_mm
    span_y = (rows - 1) * p.hole_spacing_mm + p.hole_dia_mm
    if span_x >= p.width_mm - 2 * _MIN_WALL_MM or span_y >= p.height_mm - 2 * _MIN_WALL_MM:
        out.append("hole grid extends past plate edge — reduce spacing or grow the plate")
    return out


MOUNTING_PLATE_GRID = register_subsystem(Subsystem(
    name="mounting_plate_grid",
    description="Plate with an N×M grid of through-holes — chassis mount",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("width_mm",        value=120.0, min=40.0, max=400.0, unit="mm"),
        ParamSpec("height_mm",       value=80.0,  min=40.0, max=400.0, unit="mm"),
        ParamSpec("thickness_mm",    value=4.0,   min=1.0,  max=15.0,  unit="mm"),
        ParamSpec("cols",            value=4,     min=2,    max=10,    unit="count"),
        ParamSpec("rows",            value=3,     min=2,    max=10,    unit="count"),
        ParamSpec("hole_dia_mm",     value=4.5,   min=2.0,  max=12.0,  unit="mm"),
        ParamSpec("hole_spacing_mm", value=25.0,  min=8.0,  max=80.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    fea_eligible=True,  # single Box, hole grid invariant-guaranteed clear of every edge
))
