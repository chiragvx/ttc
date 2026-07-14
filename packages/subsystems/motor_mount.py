"""Motor mount — a plate with 4 corner mounting holes and a central shaft-clearance bore."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Motor mount
A square plate with a bolt pattern at the corners (matched to a motor face) and a central bore for
the motor's shaft/boss to protrude through.
- **plate_size_mm × thickness_mm** — square plate outline + thickness.
- **bolt_pattern_mm** — centre-to-centre distance between diagonally-opposite bolts.
- **bolt_hole_dia_mm** — the four corner mounting holes.
- **center_bore_dia_mm** — clearance bore for the shaft/pilot.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    plate = bd.Box(p.plate_size_mm, p.plate_size_mm, p.thickness_mm)
    plate = plate - bd.Cylinder(radius=p.center_bore_dia_mm / 2.0, height=p.thickness_mm * 2.0)
    off = p.bolt_pattern_mm / 2.0 / math.sqrt(2.0)  # square-face bolt pattern
    tags = {
        "plate.body": {"kind": "solid", "size": [p.plate_size_mm, p.plate_size_mm, p.thickness_mm]},
        "center.bore": {"kind": "cyl_bore", "dia": p.center_bore_dia_mm},
    }
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
        plate = plate - (bd.Pos(sx * off, sy * off, 0.0)
                         * bd.Cylinder(radius=p.bolt_hole_dia_mm / 2.0, height=p.thickness_mm * 2.0))
        tags[f"bolt[{i}].bore"] = {"kind": "cyl_bore", "center": [sx * off, sy * off], "dia": p.bolt_hole_dia_mm}
    return TaggedPart(plate, tags)


def _volume(p):
    body = p.plate_size_mm * p.plate_size_mm * p.thickness_mm
    center = math.pi * (p.center_bore_dia_mm / 2.0) ** 2 * p.thickness_mm
    bolts = 4 * math.pi * (p.bolt_hole_dia_mm / 2.0) ** 2 * p.thickness_mm
    return max(0.0, body - center - bolts)


def _check(p):
    out = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.center_bore_dia_mm >= p.plate_size_mm - 2 * _MIN_WALL_MM:
        out.append("center bore too large for plate")
    if p.bolt_pattern_mm >= p.plate_size_mm * math.sqrt(2.0) - 2 * p.bolt_hole_dia_mm:
        out.append("bolt pattern falls off the plate corners")
    return out


MOTOR_MOUNT = register_subsystem(Subsystem(
    name="motor_mount",
    description="Square motor mount — 4 corner bolts + central shaft bore",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("plate_size_mm",      value=42.0, min=20.0, max=200.0, unit="mm"),
        ParamSpec("thickness_mm",       value=5.0,  min=1.0,  max=15.0,  unit="mm"),
        ParamSpec("bolt_pattern_mm",    value=31.0, min=10.0, max=180.0, unit="mm"),
        ParamSpec("bolt_hole_dia_mm",   value=3.4,  min=2.0,  max=10.0,  unit="mm"),
        ParamSpec("center_bore_dia_mm", value=22.0, min=3.0,  max=100.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    fea_eligible=True,  # single Box minus center bore + 4 corner holes, none touching the X ends
))
