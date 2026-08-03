"""Hex bar — extruded regular hexagonal cross-section (long structural stock)."""

from __future__ import annotations

import math

from packages.subsystems import InterfaceSpec, ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Hex bar
An extruded regular hexagonal bar — solid structural stock (feedstock for machining hex heads or as
wrench-shaped drive stock).
- **across_flats_mm** — key size across parallel faces.
- **length_mm** — extrusion length.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    r = p.across_flats_mm / math.sqrt(3.0)
    sketch = bd.RegularPolygon(radius=r, side_count=6)
    body = bd.extrude(sketch, amount=p.length_mm)
    return TaggedPart(body, {"bar.body": {"kind": "solid", "af": p.across_flats_mm,
                                          "length": p.length_mm}})


def _volume(p):
    hex_area = math.sqrt(3.0) / 2.0 * p.across_flats_mm ** 2
    return hex_area * p.length_mm


def _check(p):
    return []


def _end_a(p):
    """Local mate frame at the extrusion's start face -- z=0 by construction (`_build` sketches the
    hex on the default XY plane and extrudes +Z by `length_mm`, so the solid spans z=0..length_mm,
    NOT centered at the origin like `bd.Cylinder`/`bd.Box` -- confirmed live: bounding box z runs
    [0, length_mm], so neither `cylinder_end_interfaces` nor `bar_end_interfaces` (both assume
    centering) fits here). Outward normal is -Z."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, -1.0))


def _end_b(p):
    """Local mate frame at the extrusion's far face -- z=length_mm by construction. Outward normal
    is +Z."""
    from packages.subsystems.base import Frame
    return Frame(origin=(0.0, 0.0, p.length_mm), normal=(0.0, 0.0, 1.0))


HEX_BAR = register_subsystem(Subsystem(
    name="hex_bar",
    description="Solid hex bar — extruded hex cross-section",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("across_flats_mm", value=10.0,  min=3.0,  max=50.0,  unit="mm"),
        ParamSpec("length_mm",       value=100.0, min=10.0, max=500.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    # 2026-07-28 (interface-coverage sweep, final wave): `_build` extrudes the hex sketch from z=0 to
    # z=length_mm (build123d's default `extrude` behavior for a sketch on the default XY plane) --
    # NOT centered at the origin, so neither `cylinder_end_interfaces` nor `bar_end_interfaces`
    # (both assume the shape is centered on the axis they describe) apply as-is. Bespoke frames
    # computed from the part's own real z-offsets instead, same pattern as `locating_pin`'s
    # base_face/nose_face. Named `end_a`/`end_b` (not `base_face`/`tip_face`) because this is
    # symmetric feedstock like `flat_bar` (its `bar_end_interfaces` uses the same names), not a
    # directional part with one seating end and one free tip.
    interfaces=[
        InterfaceSpec(name="end_a", kind="mount", frame=_end_a),
        InterfaceSpec(name="end_b", kind="mount", frame=_end_b),
    ],
))
