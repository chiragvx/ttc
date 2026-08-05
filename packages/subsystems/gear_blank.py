"""Gear Blank -- Gear disc with hub, no teeth (spec: dp, N) (no teeth, matches the doc's own note)

Structural/mounting geometry only (`build-plan/reference/SUBSYSTEM_PROPOSALS.md` category
7) -- a plain solid cylinder. Fine surface/profile detail this part's real-world name
implies (knurling, a domed end, hex flats, a countersunk/rounded head, wing tabs, gear/sprocket
teeth) is deliberately NOT modeled -- same disclosed-simplification precedent this catalog already
established for `knurled_nut` ("approximated (no knurl grooves)"). This represents the part's
structural envelope/mounting geometry, not its full cosmetic profile.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import cylinder_end_interfaces

_FRAGMENT = """\
## Subsystem: Gear Blank
Gear disc with hub, no teeth (spec: dp, N) (no teeth, matches the doc's own note) -- a solid cylindrical body (FDM/FFF or turned). Fine surface detail (knurling, a domed
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


GEAR_BLANK = register_subsystem(Subsystem(
    name="gear_blank",
    description="Gear disc with hub, NO TEETH (spec: dp, N) -- structural/mounting geometry only, "
                 "does NOT mesh with another gear (FDM/FFF or CNC). For a part that must actually MESH "
                 "with another gear, use `spur_gear` instead -- it has real involute teeth and a working "
                 "center-distance mate solver; this part's axial mount interfaces cannot position a mesh.",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("dia_mm", value=35.0, min=10.0, max=120.0, unit='mm'),
        ParamSpec("height_mm", value=10.0, min=3.0, max=35.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    fea_eligible=True,  # plain solid cylinder, span along X-equivalent axis -- same shape class longeron.py opts into; left True here since it IS the simple validated-methodology shape, not inferred for a compound one
    # 2026-07-28 -- identical construction to round_post: bd.Cylinder(radius=dia_mm/2, height=height_mm),
    # centered at the origin along local Z by default (no rotation), so its two flat end faces are
    # exactly what cylinder_end_interfaces expects. No hub/tooth distinction is actually modeled (per
    # this file's own docstring -- a plain cylindrical envelope), so the two faces are interchangeable;
    # default "bottom"/"top" names are used, same as round_post.
    interfaces=cylinder_end_interfaces("height_mm"),
))
