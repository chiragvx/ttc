"""Box Sleeve -- Square/rect sleeve-and-collar connector joining two square-section bar/tube members
(e.g. a 20x20mm aluminum-extrusion corner sleeve -- the fitted-joint mechanism's Stage 1 rect-family
proof, `packages/subsystems/spar_joiner_sleeve.py`'s round-family Stage 0 counterpart). A rectangular
body with a concentric rectangular through-bore -- `render_box_sleeve`
(packages/truth_plane/regen/templated.py), a NEW archetype (the round family's `render_standoff` has
no rect analog yet).
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import FitSocketSpec, cylinder_end_interfaces

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Box Sleeve
Square/rect sleeve-and-collar connector that joins two square-section bar/tube members (e.g. a 20x20mm aluminum-extrusion corner joint) -- a rectangular body with a concentric rectangular through-bore (FDM/FFF or CNC).
- **outer_width_mm / outer_height_mm** -- outer cross-section.
- **bore_width_mm / bore_height_mm** -- bore cross-section (what slides over the host member).
- **height_mm** -- length along the axis.

### Intent mapping
- "for a 20x20 extrusion" -> bore_width_mm/bore_height_mm ~= 20.4 (clearance).
- "taller" / "longer" -> increase height_mm.
- "thicker wall" / "stronger" -> increase outer_width_mm/outer_height_mm (wall = (outer - bore)/2 per axis, >= 0.8 mm).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_box_sleeve
    return render_box_sleeve(outer_width_mm=p.outer_width_mm, outer_height_mm=p.outer_height_mm,
                             bore_width_mm=p.bore_width_mm, bore_height_mm=p.bore_height_mm,
                             height_mm=p.height_mm)


def _volume(p) -> float:
    outer_area = p.outer_width_mm * p.outer_height_mm
    bore_area = p.bore_width_mm * p.bore_height_mm
    return max(0.0, outer_area - bore_area) * p.height_mm


def _check(p) -> list[str]:
    issues: list[str] = []
    if p.bore_width_mm >= p.outer_width_mm:
        issues.append(f"bore_width {p.bore_width_mm:.1f} mm >= outer_width {p.outer_width_mm:.1f} mm (no wall)")
    else:
        wall_w = (p.outer_width_mm - p.bore_width_mm) / 2.0
        if wall_w < _MIN_WALL_MM:
            issues.append(f"wall_w {wall_w:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.bore_height_mm >= p.outer_height_mm:
        issues.append(f"bore_height {p.bore_height_mm:.1f} mm >= outer_height {p.outer_height_mm:.1f} mm (no wall)")
    else:
        wall_h = (p.outer_height_mm - p.bore_height_mm) / 2.0
        if wall_h < _MIN_WALL_MM:
            issues.append(f"wall_h {wall_h:.2f} mm < min wall {_MIN_WALL_MM} mm")
    return issues


BOX_SLEEVE = register_subsystem(Subsystem(
    name="box_sleeve",
    description="Square/rect sleeve-and-collar connector that joins two square-section bar/tube members -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_width_mm",  value=26.0, min=10.0, max=80.0,  unit='mm'),
        ParamSpec("outer_height_mm", value=26.0, min=10.0, max=80.0,  unit='mm'),
        ParamSpec("bore_width_mm",   value=20.4, min=5.0,  max=70.0,  unit='mm'),
        ParamSpec("bore_height_mm",  value=20.4, min=5.0,  max=70.0,  unit='mm'),
        ParamSpec("height_mm",       value=40.0, min=10.0, max=200.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # 2026-07-27 (fitted-joint mechanism, Stage 1 rect-family proof) -- can itself be chained end-to-end
    # along its own axial height_mm. NOT bar_end_interfaces: that helper assumes the named length param
    # is the box's local-X dimension (bd.Box's 1st arg); render_box_sleeve's height_mm is the 3rd
    # arg (local Z), same axis convention render_standoff/spar_joiner_sleeve use -- cylinder_end_interfaces
    # is the right helper (pure Z-axis end math, cross-section shape doesn't matter for it).
    interfaces=cylinder_end_interfaces("height_mm"),
    # this connector's bore is exactly the "sleeve wrapping a square bar/tube" case a fit_connector
    # derives from a rect-profile host -- see packages/subsystems/base.py::FitSocketSpec / fit_connector.
    fit_socket=FitSocketSpec(kind="rect", dim_params={"width_mm": "bore_width_mm", "height_mm": "bore_height_mm"}),
))
