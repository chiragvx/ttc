"""Cylindrical Grip -- Longitudinal cylindrical grip with texture ribs (texture ribs not modeled)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
11) -- a plain solid cylinder. Fine surface/profile detail this part's real-world name
implies (knurling, a domed end, hex flats, a countersunk/rounded head, wing tabs, gear/sprocket
teeth) is deliberately NOT modeled -- same disclosed-simplification precedent this catalog already
established for `knurled_nut` ("approximated (no knurl grooves)"). This represents the part's
structural envelope/mounting geometry, not its full cosmetic profile.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Cylindrical Grip
Longitudinal cylindrical grip with texture ribs (texture ribs not modeled) -- a solid cylindrical body (FDM/FFF or turned). Fine surface detail (knurling, a domed
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


CYLINDRICAL_GRIP = register_subsystem(Subsystem(
    name="cylindrical_grip",
    description="Longitudinal cylindrical grip with texture ribs -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("dia_mm", value=20.0, min=6.0, max=60.0, unit='mm'),
        ParamSpec("height_mm", value=80.0, min=20.0, max=250.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    fea_eligible=True,  # plain solid cylinder, span along X-equivalent axis -- same shape class longeron.py opts into; left True here since it IS the simple validated-methodology shape, not inferred for a compound one
))
