"""Hex Knob -- Hex-outer hand knob (hex flats not modeled)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
11) -- a plain solid cylinder. Fine surface/profile detail this part's real-world name
implies (knurling, a domed end, hex flats, a countersunk/rounded head, wing tabs, gear/sprocket
teeth) is deliberately NOT modeled -- same disclosed-simplification precedent this catalog already
established for `knurled_nut` ("approximated (no knurl grooves)"). This represents the part's
structural envelope/mounting geometry, not its full cosmetic profile.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import cylinder_end_interfaces

_FRAGMENT = """\
## Subsystem: Hex Knob
Hex-outer hand knob (hex flats not modeled) -- a solid cylindrical body (FDM/FFF or turned). Fine surface detail (knurling, a domed
end, hex flats, gear/sprocket teeth, etc.) is NOT modeled -- this represents the structural envelope.
- **dia_mm** -- overall diameter.
- **height_mm** -- overall height/length.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Cylinder(radius=p.dia_mm / 2.0, height=p.height_mm)
    return TaggedPart(body, {"body.cyl": {"kind": "solid", "dia": p.dia_mm, "height": p.height_mm}})


def _volume(p) -> float:
    import math
    return math.pi * (p.dia_mm / 2.0) ** 2 * p.height_mm


def _check(p) -> list[str]:
    if p.height_mm < 0.8:
        return [f"height {p.height_mm:.2f} mm < min wall 0.8 mm"]
    return []


HEX_KNOB = register_subsystem(Subsystem(
    name="hex_knob",
    description="Hex-outer hand knob -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("dia_mm", value=25.0, min=8.0, max=80.0, unit='mm'),
        ParamSpec("height_mm", value=15.0, min=4.0, max=45.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    fea_eligible=True,  # plain solid cylinder, span along X-equivalent axis -- same shape class longeron.py opts into; left True here since it IS the simple validated-methodology shape, not inferred for a compound one
    # 2026-07-28 (interface-coverage sweep, final wave) -- a plain bd.Cylinder(radius, height), no
    # rotation, centered at the origin along local Z (same shape/convention as round_post), so the
    # generic cylinder_end_interfaces helper applies directly. A knob's real-world mount points are
    # exactly its two flat end faces (the shaft/panel-facing bottom face and the graspable top face).
    interfaces=cylinder_end_interfaces("height_mm"),
))
