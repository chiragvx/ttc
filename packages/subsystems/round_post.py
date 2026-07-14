"""Round post — a solid cylinder (the missing complement to the hollow `standoff`)."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Round post
A solid cylinder — used as a structural column, furniture leg, display standoff (no bore).
- **dia_mm** — outer diameter.
- **height_mm** — post height.

### Intent mapping
- "solid leg" / "column" / "pillar" → this part (no through-bore; for a threaded bore use standoff).
- "taller" → increase **height_mm**; "thicker column" → increase **dia_mm**.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Cylinder(radius=p.dia_mm / 2.0, height=p.height_mm)
    return TaggedPart(body, {"post.body": {"kind": "solid", "dia": p.dia_mm, "height": p.height_mm}})


def _volume(p) -> float:
    return math.pi * (p.dia_mm / 2.0) ** 2 * p.height_mm


ROUND_POST = register_subsystem(Subsystem(
    name="round_post",
    description="Solid cylinder — structural post / furniture leg / display column",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("dia_mm",    value=12.0, min=3.0,  max=80.0,  unit="mm"),
        ParamSpec("height_mm", value=60.0, min=10.0, max=300.0, unit="mm"),
    ],
    build=_build,
    volume=_volume,
    # fea_eligible=False (default) — cylindrical geometry; the validated cantilever methodology
    # (clamp-one-end, load-other) was validated for flat plates/bars, not solid round sections.
))
