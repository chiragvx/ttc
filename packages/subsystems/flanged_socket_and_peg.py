"""Flanged Socket And Peg -- Mating socket + peg for a snap connection (represents the socket component; the mating peg is a separate simple standoff instance)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
13) -- a cylindrical shaft/boss with a wider mounting flange at its base, a concentric bore,
and an evenly-spaced bolt-hole pattern around the flange.
"""

from __future__ import annotations

import math

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Flanged Socket And Peg
Mating socket + peg for a snap connection (represents the socket component; the mating peg is a separate simple standoff instance) -- a shaft/boss on a wider mounting flange, concentric bore, flange bolt-hole pattern.
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


def _flange_face(p) -> "Frame":
    """The flange's OUTER (bottom) face, z=0 -- where this socket's flange bolts flat against a
    mounting surface (the `n_bolt_holes` pattern passes through the flange right at this face).
    Confirmed against `_build`: `flange = bd.Pos(0, 0, flange_thickness_mm/2) * bd.Cylinder(...)`,
    i.e. the flange spans z in [0, flange_thickness_mm] -- NOT centered at the origin the way
    `cylinder_end_interfaces` assumes, so that generic helper does not fit (it would compute
    +/- flange_thickness_mm/2, missing this part's real z=0 base by half the flange thickness).
    `normal` points OUTWARD (-Z, away from the solid) per `Frame`'s anti-parallel-mating convention."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _shaft_tip(p) -> "Frame":
    """The socket shaft/boss's free end -- the top face of the raised collar, at
    z = flange_thickness_mm + shaft_len_mm (the shaft sits ON TOP of the flange, per `_build`:
    `shaft = bd.Pos(0, 0, flange_thickness_mm + shaft_len_mm/2) * bd.Cylinder(...)`). This is the
    face the mating peg (a separate standoff instance) approaches. `normal` points OUTWARD (+Z)."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, p.flange_thickness_mm + p.shaft_len_mm), normal=(0.0, 0.0, 1.0))


FLANGED_SOCKET_AND_PEG = register_subsystem(Subsystem(
    name="flanged_socket_and_peg",
    description="Mating socket + peg for a snap connection -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("shaft_dia_mm", value=10.0, min=3.0, max=35.0, unit='mm'),
        ParamSpec("shaft_len_mm", value=12.0, min=3.0, max=40.0, unit='mm'),
        ParamSpec("flange_dia_mm", value=22.0, min=8.0, max=60.0, unit='mm'),
        ParamSpec("flange_thickness_mm", value=3.0, min=1.0, max=10.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=0.5, min=0.1, max=5.0, unit='mm'),
        ParamSpec("n_bolt_holes", value=0, min=0, max=4, unit='count'),
        ParamSpec("bolt_hole_dia_mm", value=2.0, min=1.0, max=5.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # 2026-07-28 (interface-coverage sweep) -- bespoke (not a shared-helper) shape: two stacked
    # cylinders (flange + shaft) offset from the origin along local Z, not a single centered
    # Cylinder/Box any existing helper covers (identical geometry to `flange_collar`, already
    # covered this way in an earlier wave -- see that file's own `_flange_face`/`_shaft_tip` for the
    # same reasoning). `flange_face` (z=0) is the real bolt-mounting face; `shaft_tip` is the socket
    # boss's free end, where the mating peg (a separate standoff instance) approaches.
    interfaces=[
        InterfaceSpec(name="flange_face", kind="mount", frame=_flange_face),
        InterfaceSpec(name="shaft_tip", kind="mount", frame=_shaft_tip),
    ],
))
