"""Bulkhead frame — a ring frame perpendicular to the fuselage axis + a bolt-hole pattern."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Bulkhead frame
A flat ring frame perpendicular to the fuselage axis — a structural cross-section frame (NOT an
aero surface), the airframe member the skin and longerons attach to at intervals along a fuselage.
- **outer_dia_mm** — outer diameter of the frame (matches the fuselage cross-section).
- **flange_width_mm** — radial width of the ring ((outer − inner) / 2); the material available to
  carry bolt loads.
- **thickness_mm** — frame thickness along the fuselage axis.
- **num_bolt_holes × bolt_hole_dia_mm** — an evenly-spaced bolt-hole pattern around the flange's
  mid-radius (e.g. for longeron or skin attachment).

### Intent mapping
- "a bulkhead for a 150mm-diameter fuselage" → outer_dia_mm=150.
- "add mounting holes for longerons" → increase **num_bolt_holes**.
- "beefier flange"/"more bearing area" → increase **flange_width_mm** (watch the bolt-hole
  edge-distance rule: bolt_hole_dia_mm ≤ flange_width_mm / 2).\
"""

_MIN_WALL_MM = 0.8  # FDM min-wall floor, packages/ledger/apply.py::MIN_WALL_MM


def _build(p):
    from packages.truth_plane.regen.templated import render_bulkhead_frame
    inner_dia_mm = max(0.1, p.outer_dia_mm - 2.0 * p.flange_width_mm)
    return render_bulkhead_frame(
        outer_dia_mm=p.outer_dia_mm, inner_dia_mm=inner_dia_mm, thickness_mm=p.thickness_mm,
        n_bolts=int(round(p.num_bolt_holes)), bolt_dia_mm=p.bolt_hole_dia_mm,
    )


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
                f"{p.outer_dia_mm:.1f} mm — reduce flange_width_mm"]
    out: list[str] = []
    if p.flange_width_mm < _MIN_WALL_MM:
        out.append(f"flange_width {p.flange_width_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    # bolt-hole edge-distance rule (bracket.py style): a hole centered on the flange's mid-radius
    # must stay clear of both the inner and outer edge — bolt_hole_dia ≤ flange_width / 2.
    max_bolt_dia = p.flange_width_mm / 2.0
    if p.bolt_hole_dia_mm > max_bolt_dia:
        out.append(f"bolt_hole_dia {p.bolt_hole_dia_mm:.1f} mm exceeds flange_width/2 "
                    f"({max_bolt_dia:.1f} mm) — edge distance violates bolted-joint rule")
    # adjacent bolt holes must not overlap around the bolt circle
    n = int(round(p.num_bolt_holes))
    mid_r = (p.outer_dia_mm + inner_dia_mm) / 4.0
    if n >= 2:
        arc_spacing = 2.0 * math.pi * mid_r / n
        if arc_spacing < p.bolt_hole_dia_mm:
            out.append(f"{n} bolt holes at dia {p.bolt_hole_dia_mm:.1f} mm on a {mid_r * 2:.1f} mm "
                        f"bolt circle overlap (spacing {arc_spacing:.1f} mm) — reduce count or hole size")
    return out


BULKHEAD_FRAME = register_subsystem(Subsystem(
    name="bulkhead_frame",
    description="Bulkhead: ring frame perpendicular to the fuselage axis + bolt-hole pattern — FDM/FFF or CNC",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_dia_mm",     value=100.0, min=40.0, max=400.0, unit="mm"),
        ParamSpec("flange_width_mm",  value=10.0,  min=3.0,  max=40.0,  unit="mm"),
        ParamSpec("thickness_mm",     value=3.0,   min=1.0,  max=10.0,  unit="mm"),
        ParamSpec("num_bolt_holes",   value=6,     min=3,    max=16,    unit="count"),
        ParamSpec("bolt_hole_dia_mm", value=4.0,   min=2.0,  max=8.0,   unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
