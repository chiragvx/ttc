"""Hex nut — regular hexagonal prism with a through-bore."""

from __future__ import annotations

import math

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Hex nut
A regular hexagonal nut — thread is not modeled; the bore is the tapped-drill diameter (a heat-set
insert or tap is added downstream). Parametric across-flats key size.
- **across_flats_mm** — wrench size (e.g. 10 mm ≈ M6 nut).
- **thickness_mm** — nut height.
- **bore_dia_mm** — through-hole (tap drill or clearance).\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    r = p.across_flats_mm / math.sqrt(3.0)  # circumradius from across-flats
    sketch = bd.RegularPolygon(radius=r, side_count=6)
    body = bd.extrude(sketch, amount=p.thickness_mm)
    body = body - bd.Cylinder(radius=p.bore_dia_mm / 2.0, height=p.thickness_mm * 2.0)
    return TaggedPart(body, {
        "nut.body": {"kind": "solid", "af": p.across_flats_mm, "h": p.thickness_mm},
        "bore.thru": {"kind": "cyl_bore", "dia": p.bore_dia_mm},
    })


def _volume(p):
    hex_area = math.sqrt(3.0) / 2.0 * p.across_flats_mm ** 2
    bore_area = math.pi * (p.bore_dia_mm / 2.0) ** 2
    return max(0.0, (hex_area - bore_area) * p.thickness_mm)


def _check(p):
    out = []
    wall = (p.across_flats_mm - p.bore_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        out.append(f"nut wall {wall:.2f} < min wall {_MIN_WALL_MM} mm")
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} < min wall {_MIN_WALL_MM} mm")
    return out


def _bottom_face(p):
    """Local mate frame at the nut's bottom face -- z=0 by construction (`_build` extrudes the hex
    sketch from z=0 to z=thickness_mm, NOT centered at the origin, unlike `cylinder_end_interfaces`'s
    +/-height/2 assumption -- confirmed live: `bd.extrude(sketch, amount=p.thickness_mm)` on a sketch
    on the default XY plane runs 0 -> amount, not centered). Outward normal points -Z (away from the
    part), matching `Frame`'s anti-parallel-touching-normals mating convention."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _top_face(p):
    """Local mate frame at the nut's top face -- z=thickness_mm by construction (the far end of the
    extrusion). Outward normal is +Z."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, p.thickness_mm), normal=(0.0, 0.0, 1.0))


HEX_NUT = register_subsystem(Subsystem(
    name="hex_nut",
    description="Hex nut — hex prism with through-bore",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("across_flats_mm", value=10.0, min=4.0, max=50.0, unit="mm"),
        ParamSpec("thickness_mm",    value=5.0,  min=1.0, max=30.0, unit="mm"),
        ParamSpec("bore_dia_mm",     value=6.0,  min=2.0, max=45.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    # 2026-07-28 (interface-coverage sweep, final wave): a hex prism extruded from a `RegularPolygon`
    # sketch on the default XY plane, z=0..thickness_mm -- NOT centered at the origin, so
    # `cylinder_end_interfaces`/`plate_face_interfaces` (both assume +/-half from center) don't fit;
    # bespoke frames computed from the part's own real z-offsets instead, same pattern as
    # `hex_bolt_blank`'s head/tip. `bottom`/`top` are the nut's two real flat bearing faces (e.g. one
    # seats against a plate, the other against a washer/bolt head).
    interfaces=[
        InterfaceSpec(name="bottom", kind="mount", frame=_bottom_face),
        InterfaceSpec(name="top", kind="mount", frame=_top_face),
    ],
))
