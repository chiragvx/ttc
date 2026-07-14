"""L-bracket subsystem — two perpendicular flanges sharing a corner."""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: L-bracket (angle)
Two perpendicular flanges meeting at a corner — an angle bracket. Geometry params:
- **leg_a_mm** — vertical flange length.
- **leg_b_mm** — horizontal flange length.
- **width_mm** — flange width (the extrusion depth).
- **thickness_mm** — flange thickness (both legs).

### Intent mapping
- "taller mounting face" → increase **leg_a_mm**; "longer base" → increase **leg_b_mm**.
- "wider"/"more bearing" → increase **width_mm**.
- "stronger"/"stiffer corner" → increase **thickness_mm** (≥ 0.8 mm).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_lbracket
    return render_lbracket(leg_a_mm=p.leg_a_mm, leg_b_mm=p.leg_b_mm,
                           width_mm=p.width_mm, thickness_mm=p.thickness_mm)


def _volume(p) -> float:
    return p.width_mm * p.thickness_mm * (p.leg_a_mm + p.leg_b_mm - p.thickness_mm)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.thickness_mm >= min(p.leg_a_mm, p.leg_b_mm):
        out.append(f"thickness {p.thickness_mm:.2f} mm ≥ a leg length (degenerate L)")
    return out


LBRACKET = register_subsystem(Subsystem(
    name="lbracket",
    description="L-shaped angle bracket (two flanges) — FDM/FFF or machined",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("leg_a_mm",       value=40.0, min=20.0, max=120.0, unit="mm"),
        ParamSpec("leg_b_mm",       value=40.0, min=20.0, max=120.0, unit="mm"),
        ParamSpec("width_mm",       value=30.0, min=10.0, max=100.0, unit="mm"),
        ParamSpec("thickness_mm",   value=3.0,  min=0.8,  max=10.0,  unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
