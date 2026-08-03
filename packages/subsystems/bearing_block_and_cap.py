"""Bearing Block And Cap -- Bearing housing + a bolted cap (represents the housing; the bolted cap is a separate plate instance)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
13) -- a cylindrical shaft/boss with a wider mounting flange at its base, a concentric bore,
and an evenly-spaced bolt-hole pattern around the flange.
"""

from __future__ import annotations

import math

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Bearing Block And Cap
Bearing housing + a bolted cap (represents the housing; the bolted cap is a separate plate instance) -- a shaft/boss on a wider mounting flange, concentric bore, flange bolt-hole pattern.
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


def _flange_face_frame(p):
    """The flange's OUTER (bottom) face, z=0 — confirmed against `_build` directly: `flange` is
    `Pos(0,0,flange_thickness_mm/2) * Cylinder(...)`, so it spans z in [0, flange_thickness_mm], NOT
    centered at the origin the way `cylinder_end_interfaces` assumes (that helper is for a lone
    cylinder centered on Z; this part is a two-diameter stack sitting ON TOP of z=0). This is the real
    mounting face -- bolted flat against a base/chassis via the `bolt[i].bore` pattern -- so its normal
    points OUTWARD/DOWNWARD (-Z)."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _shaft_top_frame(p):
    """The shaft/boss's OUTER (top) face -- the far end of the stack, at
    z = flange_thickness_mm + shaft_len_mm (confirmed against `_build`: `shaft` is
    `Pos(0,0,flange_thickness_mm + shaft_len_mm/2) * Cylinder(...)`, spanning z in
    [flange_thickness_mm, flange_thickness_mm+shaft_len_mm]). This is where the bolted cap (a separate
    plate instance per the module docstring) would mate, so its normal points OUTWARD/UPWARD (+Z)."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, p.flange_thickness_mm + p.shaft_len_mm), normal=(0.0, 0.0, 1.0))


BEARING_BLOCK_AND_CAP = register_subsystem(Subsystem(
    name="bearing_block_and_cap",
    description="Bearing housing + a bolted cap -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("shaft_dia_mm", value=18.0, min=6.0, max=55.0, unit='mm'),
        ParamSpec("shaft_len_mm", value=12.0, min=3.0, max=35.0, unit='mm'),
        ParamSpec("flange_dia_mm", value=45.0, min=14.0, max=110.0, unit='mm'),
        ParamSpec("flange_thickness_mm", value=10.0, min=3.0, max=30.0, unit='mm'),
        ParamSpec("bore_dia_mm", value=12.0, min=4.0, max=45.0, unit='mm'),
        ParamSpec("n_bolt_holes", value=4, min=0, max=6, unit='count'),
        ParamSpec("bolt_hole_dia_mm", value=5.0, min=2.0, max=10.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # 2026-07-28 (interface-coverage sweep) -- bespoke, not a shared helper: this part is a
    # two-diameter stack (flange then shaft) sitting on top of z=0, not a single cylinder centered at
    # the origin (`cylinder_end_interfaces`'s assumption) nor a box/plate. Both ends are real mount
    # points: `flange_face` bolts to a base via the flange's own bolt-hole pattern; `shaft_top` is
    # where the separate bolted cap mates.
    interfaces=[
        InterfaceSpec(name="flange_face", kind="mount", frame=_flange_face_frame),
        InterfaceSpec(name="shaft_top", kind="mount", frame=_shaft_top_frame),
    ],
))
