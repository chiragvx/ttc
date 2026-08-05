"""Threaded boss — a cylindrical mounting boss with a stepped bore (heat-set-insert receiver)."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import FitSocketSpec, cylinder_end_interfaces

_FRAGMENT = """\
## Subsystem: Threaded boss
A cylindrical mounting boss with a stepped bore — the upper bore fits a heat-set threaded insert
(matched to the fastener size), the lower bore is a smaller pilot for the fastener body.
- **outer_dia_mm** — boss OD.
- **height_mm** — total boss height.
- **insert_dia_mm × insert_depth_mm** — the upper (insert) bore.
- **pilot_dia_mm** — the lower (pilot) bore, run through to the base.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Cylinder(radius=p.outer_dia_mm / 2.0, height=p.height_mm)
    # insert bore: from top down, depth = insert_depth
    insert = bd.Pos(0.0, 0.0, p.height_mm / 2.0 - p.insert_depth_mm / 2.0 + 0.001) \
             * bd.Cylinder(radius=p.insert_dia_mm / 2.0, height=p.insert_depth_mm + 0.5)
    # pilot bore: full through (smaller)
    pilot = bd.Cylinder(radius=p.pilot_dia_mm / 2.0, height=p.height_mm * 2.0)
    return TaggedPart(body - insert - pilot, {
        "boss.body": {"kind": "solid", "od": p.outer_dia_mm, "h": p.height_mm},
        "insert.bore": {"kind": "cyl_bore", "dia": p.insert_dia_mm, "depth": p.insert_depth_mm},
        "pilot.thru": {"kind": "cyl_bore", "dia": p.pilot_dia_mm},
    })


def _volume(p):
    body = math.pi * (p.outer_dia_mm / 2.0) ** 2 * p.height_mm
    insert = math.pi * (p.insert_dia_mm / 2.0) ** 2 * p.insert_depth_mm
    pilot = math.pi * (p.pilot_dia_mm / 2.0) ** 2 * p.height_mm
    return max(0.0, body - insert - pilot)


def _check(p):
    out = []
    wall = (p.outer_dia_mm - p.insert_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        out.append(f"boss wall around insert {wall:.2f} < min wall {_MIN_WALL_MM} mm")
    if p.pilot_dia_mm >= p.insert_dia_mm:
        out.append(f"pilot_dia {p.pilot_dia_mm:.1f} ≥ insert_dia {p.insert_dia_mm:.1f} — no step")
    if p.insert_depth_mm >= p.height_mm:
        out.append("insert_depth ≥ boss height — no shoulder")
    return out


THREADED_BOSS = register_subsystem(Subsystem(
    name="threaded_boss",
    description="Cylindrical boss with a stepped bore — heat-set-insert receiver",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing"),
    params=[
        ParamSpec("outer_dia_mm",    value=10.0, min=4.0, max=40.0, unit="mm"),
        ParamSpec("height_mm",       value=12.0, min=4.0, max=50.0, unit="mm"),
        ParamSpec("insert_dia_mm",   value=5.0,  min=2.0, max=25.0, unit="mm"),
        ParamSpec("insert_depth_mm", value=6.0,  min=1.5, max=40.0, unit="mm"),
        ParamSpec("pilot_dia_mm",    value=3.4,  min=1.0, max=20.0, unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    # 2026-07-28 (interface-coverage sweep) — the boss body is `bd.Cylinder(outer_dia_mm/2, height_mm)`,
    # centered at the origin along local Z by construction (confirmed by reading `_build` above); the
    # insert/pilot bores are subtracted material, they don't change the outer envelope or move the two
    # flat end faces. `bottom` is the real seating face against whatever panel/wall the boss is printed
    # into/onto; `top` is the face the insert bore opens through, where a fastener is driven in — both
    # are genuine, useful mount points, so this matches `cylinder_end_interfaces`'s exact convention
    # (see `round_post`/`standoff` for the same reasoning applied to the cylinder-family shape).
    interfaces=cylinder_end_interfaces("height_mm"),
    # 2026-08-04 (DFM fit expansion) — CONNECTOR side: `pilot_dia_mm` is this boss's own fragment-
    # documented "smaller pilot for the fastener body" (see `_FRAGMENT` above) — the through-clearance
    # bore a screw's SHANK passes through below the insert, exactly the same "bore receives host_dia +
    # clearance_mm" shape `box_sleeve`/`spar_joiner_sleeve` already established (their own `inner_dia_mm`/
    # `bore_*_mm`), not a new mechanism. kind="round" because the pilot bore is round regardless of the
    # boss's own (also round) outer profile.
    #
    # NOT wired into fit_socket: `outer_dia_mm` (the boss OD). The cited DFM ratios — boss OD = 2x screw
    # diameter for unfilled thermoplastic, 2.5x for glass-filled (plasticmoulds.net, cross-confirmed by
    # Protolabs' independent 40-60% boss-wall-thickness figure); boss wall = 0.5-0.6x nominal wall
    # thickness (Protolabs) — see build-plan/research03aug/parametric/final_packaging_structural_design_
    # research.md section 1 — are MULTIPLICATIVE scalings of a host dimension, while `compute_fit()`'s
    # `dim_params` contract (packages/subsystems/fit.py:107) is strictly ADDITIVE
    # (`host_value + clearance_mm`). There is no `clearance_mm` that makes `host_dia + clearance_mm`
    # equal `2 * host_dia` for every host diameter, so forcing `outer_dia_mm` into `dim_params` would
    # either be wrong in general or require the caller to smuggle a ratio through a field named
    # "clearance" — flagged here per this session's own guidance rather than forced into the mechanism.
    fit_socket=FitSocketSpec(kind="round", dim_params={"dia_mm": "pilot_dia_mm"}),
))
