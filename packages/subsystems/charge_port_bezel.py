"""Charge Port Bezel -- Bezel around an external charge-port cutout

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
7) -- a flat plate with a central rectangular window/cutout plus four corner mounting
holes, the SAME shape family `panel.py` already registers (`render_panel`), reused here under this
part's own name/proportions per this catalog's established "one archetype, many named catalog
entries" convention.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Charge Port Bezel
Bezel around an external charge-port cutout -- a flat plate with a central cutout and four corner mounting holes (FDM/FFF or CNC).
- **width_mm x height_mm** -- plate footprint.
- **thickness_mm** -- plate thickness.
- **window_w_mm x window_h_mm** -- the central cutout (must stay smaller than the plate).
- **hole_dia_mm x hole_margin_mm** -- four corner mounting holes, inset by hole_margin_mm.

### Intent mapping
- "bigger opening" -> increase window_w_mm/window_h_mm.
- "stronger" / "stiffer" -> increase thickness_mm (0.8 mm floor).
- "for M3 bolts" -> hole_dia_mm ~= 3.4 ("M4" ~= 4.5).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_panel
    return render_panel(width_mm=p.width_mm, height_mm=p.height_mm, thickness_mm=p.thickness_mm,
                       window_w_mm=p.window_w_mm, window_h_mm=p.window_h_mm,
                       hole_dia_mm=p.hole_dia_mm, hole_margin_mm=p.hole_margin_mm)


def _volume(p) -> float:
    plate_v = p.width_mm * p.height_mm * p.thickness_mm
    window_v = min(p.window_w_mm, p.width_mm) * min(p.window_h_mm, p.height_mm) * p.thickness_mm
    hole_v = 4 * 3.14159265 * (p.hole_dia_mm / 2.0) ** 2 * p.thickness_mm
    return max(0.0, plate_v - window_v - hole_v)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.window_w_mm >= p.width_mm or p.window_h_mm >= p.height_mm:
        out.append(f"window {p.window_w_mm:.1f}x{p.window_h_mm:.1f} mm does not fit inside the "
                   f"{p.width_mm:.1f}x{p.height_mm:.1f} mm plate")
    return out


CHARGE_PORT_BEZEL = register_subsystem(Subsystem(
    name="charge_port_bezel",
    description="Bezel around an external charge-port cutout -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("width_mm", value=30.0, min=10.0, max=100.0, unit='mm'),
        ParamSpec("height_mm", value=20.0, min=6.0, max=80.0, unit='mm'),
        ParamSpec("thickness_mm", value=3.0, min=0.8, max=12.0, unit='mm'),
        ParamSpec("window_w_mm", value=12.0, min=3.0, max=50.0, unit='mm'),
        ParamSpec("window_h_mm", value=8.0, min=2.0, max=40.0, unit='mm'),
        ParamSpec("hole_dia_mm", value=2.5, min=1.2, max=6.0, unit='mm'),
        ParamSpec("hole_margin_mm", value=4.0, min=1.5, max=15.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
