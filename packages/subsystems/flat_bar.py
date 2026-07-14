"""Flat bar — solid rectangular bar (a structural section)."""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Flat bar
A solid rectangular bar — a workhorse structural section (tie-plates, links, brackets stock).
- **length_mm × width_mm × thickness_mm** — cross-section extruded along length.\
"""

_MIN_WALL_MM = 0.8


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Box(p.length_mm, p.width_mm, p.thickness_mm)
    return TaggedPart(body, {"bar.body": {"kind": "solid",
                                          "size": [p.length_mm, p.width_mm, p.thickness_mm]}})


def _volume(p):
    return p.length_mm * p.width_mm * p.thickness_mm


def _check(p):
    if p.thickness_mm < _MIN_WALL_MM:
        return [f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


FLAT_BAR = register_subsystem(Subsystem(
    name="flat_bar",
    description="Solid rectangular flat bar — structural section",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",    value=100.0, min=20.0, max=500.0, unit="mm"),
        ParamSpec("width_mm",     value=20.0,  min=5.0,  max=100.0, unit="mm"),
        ParamSpec("thickness_mm", value=5.0,   min=0.8,  max=30.0,  unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    fea_eligible=True,  # single Box, span along X — the validated cantilever methodology applies as-is
))
