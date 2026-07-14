"""U-channel subsystem — an extruded channel section (base + two side walls)."""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: U-channel
An extruded channel — a base with two upstanding side walls (open top, open both ends). Geometry params:
- **length_mm** — how long the channel runs.
- **width_mm** — outer width across the U.
- **height_mm** — outer wall height.
- **wall_thickness_mm** — base & side-wall thickness (≥ 0.8 mm).

### Intent mapping
- "longer rail" → increase **length_mm**; "deeper channel" → increase **height_mm**.
- "wider slot" → increase **width_mm** (usable inner width = width − 2×wall).
- "stronger"/"stiffer" → increase **wall_thickness_mm**.\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_uchannel
    return render_uchannel(length_mm=p.length_mm, width_mm=p.width_mm,
                           height_mm=p.height_mm, wall_mm=p.wall_thickness_mm)


def _volume(p) -> float:
    L, W, H, t = p.length_mm, p.width_mm, p.height_mm, p.wall_thickness_mm
    return L * W * H - L * max(0.0, W - 2 * t) * max(0.0, H - t)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.wall_thickness_mm < _MIN_WALL_MM:
        out.append(f"wall_thickness {p.wall_thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if 2 * p.wall_thickness_mm >= p.width_mm:
        out.append(f"wall_thickness {p.wall_thickness_mm:.2f} mm ×2 leaves no channel in a "
                   f"{p.width_mm:.0f} mm width")
    if p.wall_thickness_mm >= p.height_mm:
        out.append(f"wall_thickness {p.wall_thickness_mm:.2f} mm ≥ height {p.height_mm:.0f} mm")
    return out


UCHANNEL = register_subsystem(Subsystem(
    name="uchannel",
    description="Extruded U-channel (base + two side walls) — FDM/FFF or extruded/machined",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",          value=80.0, min=20.0, max=200.0, unit="mm"),
        ParamSpec("width_mm",           value=40.0, min=10.0, max=120.0, unit="mm"),
        ParamSpec("height_mm",          value=25.0, min=5.0,  max=100.0, unit="mm"),
        ParamSpec("wall_thickness_mm",  value=3.0,  min=0.8,  max=10.0,  unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
