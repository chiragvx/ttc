"""Threaded boss — a cylindrical mounting boss with a stepped bore (heat-set-insert receiver)."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Threaded boss
A cylindrical mounting boss with a stepped bore — the upper bore fits a heat-set threaded insert
(matched to the fastener size), the lower bore is a smaller pilot for the fastener body.
- **outer_dia_mm** — boss OD.
- **height_mm** — total boss height.
- **insert_dia_mm × insert_depth_mm** — the upper (insert) bore.
- **pilot_dia_mm** — the lower (pilot) bore, run through to the base.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Cylinder(radius=p.outer_dia_mm / 2.0, height=p.height_mm)
    # insert bore: from top down, depth = insert_depth
    insert = bd.Pos(0.0, 0.0, p.height_mm / 2.0 - p.insert_depth_mm / 2.0 + 0.001) \
             * bd.Cylinder(radius=p.insert_dia_mm / 2.0, height=p.insert_depth_mm + 0.5)
    # pilot bore: full through (smaller)
    pilot = bd.Cylinder(radius=p.pilot_dia_mm / 2.0, height=p.height_mm * 2.0)
    return TaggedPart(body - insert - pilot, {
        "boss.body": {"kind": "solid", "od": p.outer_dia_mm, "h": p.height_mm},
        "insert.bore": {"kind": "cyl_bore", "dia": p.insert_dia_mm, "depth": p.insert_depth_mm},
        "pilot.thru": {"kind": "cyl_bore", "dia": p.pilot_dia_mm},
    })


def _volume(p):
    body = math.pi * (p.outer_dia_mm / 2.0) ** 2 * p.height_mm
    insert = math.pi * (p.insert_dia_mm / 2.0) ** 2 * p.insert_depth_mm
    pilot = math.pi * (p.pilot_dia_mm / 2.0) ** 2 * p.height_mm
    return max(0.0, body - insert - pilot)


def _check(p):
    out = []
    wall = (p.outer_dia_mm - p.insert_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        out.append(f"boss wall around insert {wall:.2f} < min wall {_MIN_WALL_MM} mm")
    if p.pilot_dia_mm >= p.insert_dia_mm:
        out.append(f"pilot_dia {p.pilot_dia_mm:.1f} ≥ insert_dia {p.insert_dia_mm:.1f} — no step")
    if p.insert_depth_mm >= p.height_mm:
        out.append("insert_depth ≥ boss height — no shoulder")
    return out


THREADED_BOSS = register_subsystem(Subsystem(
    name="threaded_boss",
    description="Cylindrical boss with a stepped bore — heat-set-insert receiver",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("outer_dia_mm",    value=10.0, min=4.0, max=40.0, unit="mm"),
        ParamSpec("height_mm",       value=12.0, min=4.0, max=50.0, unit="mm"),
        ParamSpec("insert_dia_mm",   value=5.0,  min=2.0, max=25.0, unit="mm"),
        ParamSpec("insert_depth_mm", value=6.0,  min=1.5, max=40.0, unit="mm"),
        ParamSpec("pilot_dia_mm",    value=3.4,  min=1.0, max=20.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
