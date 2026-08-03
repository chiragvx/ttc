"""Dowel pin — solid cylinder for alignment/locating."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import cylinder_end_interfaces

_FRAGMENT = """\
## Subsystem: Dowel pin
A solid cylindrical pin — alignment/locating between two mating parts.
- **dia_mm** — pin diameter (fits a matching bore).
- **length_mm** — pin length.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Cylinder(radius=p.dia_mm / 2.0, height=p.length_mm)
    return TaggedPart(body, {"pin.body": {"kind": "solid", "dia": p.dia_mm, "length": p.length_mm}})


def _volume(p):
    return math.pi * (p.dia_mm / 2.0) ** 2 * p.length_mm


def _check(p):
    if p.length_mm < p.dia_mm:
        return [f"length {p.length_mm:.1f} < dia {p.dia_mm:.1f} — proportionally a disc, not a pin"]
    return []


DOWEL_PIN = register_subsystem(Subsystem(
    name="dowel_pin",
    description="Solid cylindrical dowel/locating pin",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("dia_mm",    value=5.0,  min=1.0, max=25.0,  unit="mm"),
        ParamSpec("length_mm", value=20.0, min=3.0, max=150.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    # 2026-07-28 — a solid cylinder built via bd.Cylinder(radius, height=p.length_mm), centered on the
    # origin along local Z by build123d's default (same convention confirmed for round_post/etc), so
    # its two flat end faces are exactly what cylinder_end_interfaces expects. A dowel pin mates
    # between two parts' bores by its two ends — no bottom/top asymmetry to name around, so the
    # helper's default names are kept as-is.
    interfaces=cylinder_end_interfaces("length_mm"),
))
