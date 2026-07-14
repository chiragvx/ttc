"""T-bar — extruded T cross-section (web + flange)."""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: T-bar
An extruded T cross-section — a stiffened rail.
- **length_mm** — extrusion length.
- **flange_width_mm × flange_thickness_mm** — the top of the T (crossbar).
- **web_height_mm × web_thickness_mm** — the vertical stem.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    # flange (crossbar) sits on top; web hangs below
    flange = bd.Pos(0.0, 0.0, p.web_height_mm + p.flange_thickness_mm / 2.0) \
             * bd.Box(p.length_mm, p.flange_width_mm, p.flange_thickness_mm)
    web = bd.Pos(0.0, 0.0, p.web_height_mm / 2.0) \
          * bd.Box(p.length_mm, p.web_thickness_mm, p.web_height_mm)
    return TaggedPart(flange + web, {
        "flange.body": {"kind": "solid"},
        "web.body": {"kind": "solid"},
    })


def _volume(p):
    return p.length_mm * (p.flange_width_mm * p.flange_thickness_mm
                          + p.web_thickness_mm * p.web_height_mm)


def _check(p):
    out = []
    if min(p.flange_thickness_mm, p.web_thickness_mm) < _MIN_WALL_MM:
        out.append(f"a thickness < min wall {_MIN_WALL_MM} mm")
    if p.web_thickness_mm >= p.flange_width_mm:
        out.append("web wider than flange — degenerate T")
    return out


T_BAR = register_subsystem(Subsystem(
    name="t_bar",
    description="Extruded T cross-section — structural rail",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",           value=100.0, min=20.0, max=500.0, unit="mm"),
        ParamSpec("flange_width_mm",     value=30.0,  min=8.0,  max=120.0, unit="mm"),
        ParamSpec("flange_thickness_mm", value=3.0,   min=0.8,  max=15.0,  unit="mm"),
        ParamSpec("web_height_mm",       value=20.0,  min=5.0,  max=100.0, unit="mm"),
        ParamSpec("web_thickness_mm",    value=3.0,   min=0.8,  max=15.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
