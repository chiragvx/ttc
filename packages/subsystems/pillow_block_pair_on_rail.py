"""Pillow Block Pair On Rail -- Two pillow blocks on a rectangular rail (represents one pillow block; the rail is a separate existing subsystem (square_tube/flat_bar), the second block a repeated instance)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
13) -- a cylindrical shaft/boss with a wider mounting flange at its base, a concentric bore,
and an evenly-spaced bolt-hole pattern around the flange.
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Pillow Block Pair On Rail
Two pillow blocks on a rectangular rail (represents one pillow block; the rail is a separate existing subsystem (square_tube/flat_bar), the second block a repeated instance) -- a shaft/boss on a wider mounting flange, concentric bore, flange bolt-hole pattern.
- **shaft_dia_mm x shaft_len_mm** -- the raised boss/collar.
- **flange_dia_mm x flange_thickness_mm** -- the mounting flange.
- **bore_dia_mm** -- concentric through-bore.
- **n_bolt_holes x bolt_hole_dia_mm** -- evenly spaced around the flange.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    flange = bd.Pos(0, 0, p.flange_thickness_mm / 2.0) * bd.Cylinder(radius=p.flange_dia_mm / 2.0, height=p.flange_thickness_mm)
    shaft = bd.Pos(0, 0, p.flange_thickness_mm + p.shaft_len_mm / 2.0) * bd.Cylinder(radius=p.shaft_dia_mm / 2.0, height=p.shaft_len_mm)
    part = flange + shaft
    part = part - bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=(p.flange_thickness_mm + p.shaft_len_mm) * 2.0)
    tags = {
        "flange.body": {"kind": "solid", "dia": p.flange_dia_mm},
        "shaft.body": {"kind": "solid", "dia": p.shaft_dia_mm},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
    }
    n = int(round(p.n_bolt_holes))
    mid_r = p.flange_dia_mm / 2.0 * 0.75
    for i in range(n):
        theta = 2.0 * math.pi * i / n
        x, y = mid_r * math.cos(theta), mid_r * math.sin(theta)
        part = part - (bd.Pos(x, y, p.flange_thickness_mm / 2.0) * bd.Cylinder(radius=p.bolt_hole_dia_mm / 2.0, height=p.flange_thickness_mm * 2.0))
        tags[f"bolt[{i}].bore"] = {"kind": "cyl_bore", "center": [x, y], "dia": p.bolt_hole_dia_mm}
    return TaggedPart(part, tags)


def _volume(p) -> float:
    flange_v = math.pi * (p.flange_dia_mm / 2.0) ** 2 * p.flange_thickness_mm
    shaft_v = math.pi * (p.shaft_dia_mm / 2.0) ** 2 * p.shaft_len_mm
    bore_v = math.pi * (p.bore_dia_mm / 2.0) ** 2 * (p.flange_thickness_mm + p.shaft_len_mm)
    n = int(round(p.n_bolt_holes))
    holes_v = n * math.pi * (p.bolt_hole_dia_mm / 2.0) ** 2 * p.flange_thickness_mm
    return max(0.0, flange_v + shaft_v - bore_v - holes_v)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.bore_dia_mm >= p.shaft_dia_mm:
        out.append(f"bore_dia {p.bore_dia_mm:.1f} mm >= shaft_dia (no wall)")
    if p.flange_dia_mm <= p.shaft_dia_mm:
        out.append(f"flange_dia {p.flange_dia_mm:.1f} mm must exceed shaft_dia (no flange overhang)")
    max_bolt_dia = (p.flange_dia_mm - p.shaft_dia_mm) / 4.0
    if p.bolt_hole_dia_mm > max_bolt_dia:
        out.append(f"bolt_hole_dia {p.bolt_hole_dia_mm:.1f} mm too large for the flange overhang -- "
                    f"reduce bolt_hole_dia_mm or increase flange_dia_mm")
    return out


PILLOW_BLOCK_PAIR_ON_RAIL = register_subsystem(Subsystem(
    name="pillow_block_pair_on_rail",
    description="Two pillow blocks on a rectangular rail -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("shaft_dia_mm", value=16.0, min=5.0, max=50.0, unit='mm'),
        ParamSpec("shaft_len_mm", value=8.0, min=2.0, max=25.0, unit='mm'),
        ParamSpec("flange_dia_mm", value=40.0, min=12.0, max=100.0, unit='mm'),
        ParamSpec("flange_thickness_mm", value=10.0, min=3.0, max=30.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=10.0, min=3.0, max=40.0, unit='mm'),
        ParamSpec("n_bolt_holes", value=2, min=0, max=4, unit='count'),
        ParamSpec("bolt_hole_dia_mm", value=5.0, min=2.0, max=10.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
