"""Z-bracket — three flanges in a Z shape (two horizontal legs offset by a vertical connector)."""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Z-bracket
Three flanges in a Z pattern — mounts one plane offset above another (offset shelf brackets).
- **top_length_mm × top_width_mm** — upper flange (typically the mounting face).
- **connector_height_mm** — the vertical offset between the two horizontal faces.
- **bottom_length_mm × bottom_width_mm** — lower flange.
- **thickness_mm** — same across all three legs.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    t = p.thickness_mm
    top = bd.Pos(-p.top_length_mm / 2.0, 0.0, p.connector_height_mm + t / 2.0) \
          * bd.Box(p.top_length_mm, p.top_width_mm, t)
    conn = bd.Pos(-t / 2.0, 0.0, p.connector_height_mm / 2.0) \
           * bd.Box(t, p.top_width_mm, p.connector_height_mm)
    bot = bd.Pos(p.bottom_length_mm / 2.0, 0.0, t / 2.0) \
          * bd.Box(p.bottom_length_mm, p.bottom_width_mm, t)
    return TaggedPart(top + conn + bot, {
        "top.flange": {"kind": "solid"},
        "connector.body": {"kind": "solid"},
        "bottom.flange": {"kind": "solid"},
    })


def _volume(p):
    t = p.thickness_mm
    return (p.top_length_mm * p.top_width_mm * t
            + t * max(p.top_width_mm, p.bottom_width_mm) * p.connector_height_mm
            + p.bottom_length_mm * p.bottom_width_mm * t)


def _check(p):
    if p.thickness_mm < _MIN_WALL_MM:
        return [f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


Z_BRACKET = register_subsystem(Subsystem(
    name="z_bracket",
    description="Three-flange Z bracket — offset shelf mount",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("top_length_mm",       value=40.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("top_width_mm",        value=30.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("connector_height_mm", value=30.0, min=5.0,  max=200.0, unit="mm"),
        ParamSpec("bottom_length_mm",    value=40.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("bottom_width_mm",     value=30.0, min=10.0, max=200.0, unit="mm"),
        ParamSpec("thickness_mm",        value=3.0,  min=0.8,  max=15.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
))
