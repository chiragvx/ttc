"""Round post — a solid cylinder (the missing complement to the hollow `standoff`)."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import FitProfile, cylinder_end_interfaces

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
    # 2026-07-27 (fitted-joint mechanism, Stage 0 round-family proof) — this post's own diameter is a
    # real cross-section a connector (a sleeve, a collar) can be fitted around. See
    # packages/subsystems/base.py::FitProfile / fit_connector.
    fit_profile=lambda p: FitProfile(kind="round", dims={"dia_mm": p.dia_mm}),
    # 2026-07-27 — this part previously declared ZERO mate interfaces despite being one of the most
    # common members in a multi-part assembly (a leg/post between two shelves/plates); it could never
    # actually MATE via connection_ops, only ever sit at an auto-layout/hand-computed position. A
    # cylinder built via bd.Cylinder stands along local Z by default (no rotation needed, confirmed
    # live this session), so its two flat end faces are exactly what cylinder_end_interfaces expects.
    interfaces=cylinder_end_interfaces("height_mm"),
))
