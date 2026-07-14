"""Panel / faceplate subsystem — a flat plate with a rectangular window and corner mounting holes."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8
_BORDER_MM = 8.0  # min frame each side of the window

_FRAGMENT = """\
## Subsystem: Panel / faceplate
A flat plate with a central rectangular window (a display/connector cutout) and four corner mounting
holes. Geometry params:
- **width_mm × height_mm** — the plate outline.
- **thickness_mm** — plate thickness (≥ 0.8 mm).
- **window_width_mm × window_height_mm** — the central cutout (must leave an ~8 mm frame each side).
- **hole_dia_mm** — the four corner mounting holes (M3 clearance ≈ 3.4, M4 ≈ 4.5).

### Intent mapping
- "bigger screen cutout" → increase **window_width_mm / window_height_mm** (stay inside the frame).
- "for a 7-inch display" → size the window to the bezel; keep a frame for the corner holes.
- "M4 mounting" → **hole_dia_mm** = 4.5.\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_panel
    return render_panel(width_mm=p.width_mm, height_mm=p.height_mm,
                        thickness_mm=p.thickness_mm, window_w_mm=p.window_width_mm,
                        window_h_mm=p.window_height_mm, hole_dia_mm=p.hole_dia_mm)


def _volume(p) -> float:
    window = p.window_width_mm * p.window_height_mm * p.thickness_mm
    holes = 4 * math.pi * (p.hole_dia_mm / 2.0) ** 2 * p.thickness_mm
    return max(0.0, p.width_mm * p.height_mm * p.thickness_mm - window - holes)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.window_width_mm > p.width_mm - 2 * _BORDER_MM:
        out.append(f"window_width {p.window_width_mm:.0f} mm leaves < {_BORDER_MM:.0f} mm frame")
    if p.window_height_mm > p.height_mm - 2 * _BORDER_MM:
        out.append(f"window_height {p.window_height_mm:.0f} mm leaves < {_BORDER_MM:.0f} mm frame")
    return out


PANEL = register_subsystem(Subsystem(
    name="panel",
    description="Faceplate: flat plate with a window cutout + corner mounting holes — FDM/FFF or CNC",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("width_mm",         value=100.0, min=40.0, max=300.0, unit="mm"),
        ParamSpec("height_mm",        value=80.0,  min=40.0, max=300.0, unit="mm"),
        ParamSpec("thickness_mm",     value=3.0,   min=1.0,  max=10.0,  unit="mm"),
        ParamSpec("window_width_mm",  value=60.0,  min=5.0,  max=250.0, unit="mm"),
        ParamSpec("window_height_mm", value=40.0,  min=5.0,  max=250.0, unit="mm"),
        ParamSpec("hole_dia_mm",      value=4.0,   min=2.0,  max=10.0,  unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    fea_eligible=True,  # single Box, window + corner holes all inset from the X-extreme faces
))
