"""Tensioner Bracket -- Bracket anchoring a tensioning cable/wire

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
13) -- two perpendicular flanges sharing a corner, the SAME shape family `lbracket.py`
already registers (`render_lbracket`), reused here under this part's own name/proportions per this
catalog's established "one archetype, many named catalog entries" convention.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Tensioner Bracket
Bracket anchoring a tensioning cable/wire -- an angle bracket, two perpendicular flanges meeting at a corner (FDM/FFF or machined).
- **leg_a_mm** -- vertical flange length.
- **leg_b_mm** -- horizontal flange length.
- **width_mm** -- flange width (the extrusion depth).
- **thickness_mm** -- flange thickness (both legs).

### Intent mapping
- "taller mounting face" -> increase leg_a_mm; "longer base" -> increase leg_b_mm.
- "wider" / "more bearing" -> increase width_mm.
- "stronger" / "stiffer corner" -> increase thickness_mm (0.8 mm floor).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_lbracket
    return render_lbracket(leg_a_mm=p.leg_a_mm, leg_b_mm=p.leg_b_mm, width_mm=p.width_mm,
                           thickness_mm=p.thickness_mm)


def _volume(p) -> float:
    return p.width_mm * p.thickness_mm * (p.leg_a_mm + p.leg_b_mm - p.thickness_mm)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.thickness_mm >= min(p.leg_a_mm, p.leg_b_mm):
        out.append(f"thickness {p.thickness_mm:.2f} mm >= a leg length (degenerate L)")
    return out


TENSIONER_BRACKET = register_subsystem(Subsystem(
    name="tensioner_bracket",
    description="Bracket anchoring a tensioning cable/wire -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("leg_a_mm", value=18.0, min=8.0, max=60.0, unit='mm'),
        ParamSpec("leg_b_mm", value=18.0, min=8.0, max=60.0, unit='mm'),
        ParamSpec("width_mm", value=12.0, min=5.0, max=50.0, unit='mm'),
        ParamSpec("thickness_mm", value=2.5, min=0.8, max=10.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
