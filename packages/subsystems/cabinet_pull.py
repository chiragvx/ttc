"""Cabinet Pull -- Cabinet-drawer pull (two mounting posts + span)

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
11) -- an extruded U-channel (base + two side walls, open top and both ends), the SAME
shape family `uchannel.py` already registers (`render_uchannel`), reused here under this part's own
name/proportions per this catalog's established "one archetype, many named catalog entries"
convention.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Cabinet Pull
Cabinet-drawer pull (two mounting posts + span) -- an extruded U-channel, open at the top and both ends (FDM/FFF or extruded stock).
- **length_mm** -- extrusion length.
- **width_mm x height_mm** -- outer cross-section.
- **wall_mm** -- wall thickness (base + both side walls).

### Intent mapping
- "longer" -> increase length_mm.
- "deeper channel" -> increase height_mm; "wider channel" -> increase width_mm.
- "stronger" / "stiffer" -> increase wall_mm (0.8 mm floor).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_uchannel
    return render_uchannel(length_mm=p.length_mm, width_mm=p.width_mm, height_mm=p.height_mm,
                           wall_mm=p.wall_mm)


def _volume(p) -> float:
    outer_v = p.length_mm * p.width_mm * p.height_mm
    cav_w = max(0.0, p.width_mm - 2.0 * p.wall_mm)
    cav_h = max(0.0, p.height_mm - p.wall_mm)
    return max(0.0, outer_v - p.length_mm * cav_w * cav_h)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.wall_mm < _MIN_WALL_MM:
        out.append(f"wall {p.wall_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if 2 * p.wall_mm >= p.width_mm:
        out.append(f"wall_mm x2 leaves no channel in a {p.width_mm:.0f} mm width")
    if p.wall_mm >= p.height_mm:
        out.append(f"wall_mm >= height_mm -- no open channel depth left")
    return out


CABINET_PULL = register_subsystem(Subsystem(
    name="cabinet_pull",
    description="Cabinet-drawer pull (two mounting posts + span) -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm", value=96.0, min=20.0, max=300.0, unit='mm'),
        ParamSpec("width_mm", value=12.0, min=4.0, max=35.0, unit='mm'),
        ParamSpec("height_mm", value=25.0, min=6.0, max=70.0, unit='mm'),
        ParamSpec("wall_mm", value=4.0, min=1.0, max=15.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
