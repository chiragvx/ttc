"""Junction Box -- Enclosure + cable-gland pass-through bosses + mounting flanges (gland bosses/flanges not modeled)

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
3) -- an open-top rectangular shell, the SAME shape family `enclosure.py` already
registers (`render_enclosure`), reused here under this part's own name/proportions per this
catalog's established "one archetype, many named catalog entries" convention.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Junction Box
Enclosure + cable-gland pass-through bosses + mounting flanges (gland bosses/flanges not modeled) -- an open-top rectangular shell (FDM/FFF), a floor of thickness wall_mm, open at the
top for a mating lid/cover.
- **width_mm x depth_mm x height_mm** -- outer envelope.
- **wall_mm** -- shell wall thickness (all sides + floor).

### Intent mapping
- "bigger" -> increase width_mm/depth_mm/height_mm.
- "stronger" / "thicker walls" -> increase wall_mm (0.8 mm floor).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_enclosure
    return render_enclosure(width_mm=p.width_mm, depth_mm=p.depth_mm, height_mm=p.height_mm, wall_mm=p.wall_mm)


def _volume(p) -> float:
    outer_v = p.width_mm * p.depth_mm * p.height_mm
    inner_w = max(0.0, p.width_mm - 2.0 * p.wall_mm)
    inner_d = max(0.0, p.depth_mm - 2.0 * p.wall_mm)
    inner_h = max(0.0, p.height_mm - p.wall_mm)
    return max(0.0, outer_v - inner_w * inner_d * inner_h)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.wall_mm < _MIN_WALL_MM:
        out.append(f"wall {p.wall_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if 2 * p.wall_mm >= min(p.width_mm, p.depth_mm):
        out.append(f"wall_mm x2 leaves no interior cavity")
    return out


JUNCTION_BOX = register_subsystem(Subsystem(
    name="junction_box",
    description="Enclosure + cable-gland pass-through bosses + mounting flanges -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("width_mm", value=75.0, min=20.0, max=240.0, unit='mm'),
        ParamSpec("depth_mm", value=55.0, min=15.0, max=190.0, unit='mm'),
        ParamSpec("height_mm", value=40.0, min=10.0, max=140.0, unit='mm'),
        ParamSpec("wall_mm", value=2.5, min=0.8, max=10.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    fea_eligible=False,
))
