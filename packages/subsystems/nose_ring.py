"""Nose Ring -- Forward-most bulkhead ring, mount point for nose cone/payload

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
1) -- a flat ring frame + evenly-spaced bolt-hole pattern, the SAME shape family
`bulkhead_frame.py` already registers (`render_bulkhead_frame`), reused here under this part's own
name/proportions per this catalog's established "one archetype, many named catalog entries"
convention.
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Nose Ring
Forward-most bulkhead ring, mount point for nose cone/payload -- a flat ring frame perpendicular to the fuselage axis (FDM/FFF or CNC).
- **outer_dia_mm** -- outer diameter of the frame.
- **flange_width_mm** -- radial width of the ring ((outer - inner) / 2).
- **thickness_mm** -- frame thickness along the axis.
- **num_bolt_holes x bolt_hole_dia_mm** -- an evenly-spaced bolt-hole pattern around the flange's
  mid-radius.

### Intent mapping
- "for a 100mm-diameter fuselage" -> outer_dia_mm ~= 100.
- "beefier flange" / "more bearing area" -> increase flange_width_mm (watch bolt_hole_dia_mm <=
  flange_width_mm / 2).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_bulkhead_frame
    inner_dia_mm = max(0.1, p.outer_dia_mm - 2.0 * p.flange_width_mm)
    return render_bulkhead_frame(outer_dia_mm=p.outer_dia_mm, inner_dia_mm=inner_dia_mm,
                                 thickness_mm=p.thickness_mm, n_bolts=int(round(p.num_bolt_holes)),
                                 bolt_dia_mm=p.bolt_hole_dia_mm)


def _volume(p) -> float:
    inner_dia_mm = max(0.0, p.outer_dia_mm - 2.0 * p.flange_width_mm)
    ro, ri = p.outer_dia_mm / 2.0, inner_dia_mm / 2.0
    ring_vol = math.pi * max(0.0, ro * ro - ri * ri) * p.thickness_mm
    n = int(round(p.num_bolt_holes))
    bolt_vol = n * math.pi * (p.bolt_hole_dia_mm / 2.0) ** 2 * p.thickness_mm
    return max(0.0, ring_vol - bolt_vol)


def _check(p) -> list[str]:
    inner_dia_mm = p.outer_dia_mm - 2.0 * p.flange_width_mm
    if inner_dia_mm <= 0.0:
        return [f"flange_width {p.flange_width_mm:.1f} mm leaves no inner diameter for outer_dia "
                f"{p.outer_dia_mm:.1f} mm -- reduce flange_width_mm"]
    out: list[str] = []
    if p.flange_width_mm < _MIN_WALL_MM:
        out.append(f"flange_width {p.flange_width_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    max_bolt_dia = p.flange_width_mm / 2.0
    if p.bolt_hole_dia_mm > max_bolt_dia:
        out.append(f"bolt_hole_dia {p.bolt_hole_dia_mm:.1f} mm exceeds flange_width/2 "
                    f"({max_bolt_dia:.1f} mm) -- edge distance violates bolted-joint rule")
    n = int(round(p.num_bolt_holes))
    mid_r = (p.outer_dia_mm + inner_dia_mm) / 4.0
    if n >= 2:
        arc_spacing = 2.0 * math.pi * mid_r / n
        if arc_spacing < p.bolt_hole_dia_mm:
            out.append(f"{n} bolt holes at dia {p.bolt_hole_dia_mm:.1f} mm on a {mid_r * 2:.1f} mm "
                        f"bolt circle overlap (spacing {arc_spacing:.1f} mm) -- reduce count or hole size")
    return out


NOSE_RING = register_subsystem(Subsystem(
    name="nose_ring",
    description="Forward-most bulkhead ring, mount point for nose cone/payload -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_dia_mm", value=90.0, min=40.0, max=300.0, unit='mm'),
        ParamSpec("flange_width_mm", value=10.0, min=3.0, max=30.0, unit='mm'),
        ParamSpec("thickness_mm", value=3.0, min=1.0, max=10.0, unit='mm'),
        ParamSpec("num_bolt_holes", value=6, min=3, max=16, unit='count'),
        ParamSpec("bolt_hole_dia_mm", value=3.4, min=2.0, max=8.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
