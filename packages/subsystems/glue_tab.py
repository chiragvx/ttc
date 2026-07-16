"""Glue Tab -- Small flat tab sized for a bonded joint

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
13) -- a flat mounting plate with a row of bolt holes, the SAME shape family
`bracket.py` already registers (`render_bracket`), reused here under this part's own name/proportions
per this catalog's established "one archetype, many named catalog entries" convention (see
`standoff.py`/`washer.py`: the washer subsystem already reuses the standoff generator the same way).
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Glue Tab
Small flat tab sized for a bonded joint -- a flat plate with a row of bolt holes (FDM/FFF or CNC).
- **width_mm x depth_mm** -- plate footprint.
- **thickness_mm** -- plate thickness.
- **hole_dia_mm x n_holes x margin_mm** -- an evenly-spaced bolt-hole row (margin from each edge).

### Intent mapping
- "bigger" / "more mounting area" -> increase width_mm/depth_mm.
- "stronger" / "stiffer" -> increase thickness_mm (0.8 mm floor).
- "more mounting points" -> increase n_holes; "for M3 bolts" -> hole_dia_mm ~= 3.4 ("M4" ~= 4.5).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_bracket
    return render_bracket(width_mm=p.width_mm, depth_mm=p.depth_mm, thickness_mm=p.thickness_mm,
                          hole_dia_mm=p.hole_dia_mm, n_holes=int(round(p.n_holes)), margin_mm=p.margin_mm)


def _volume(p) -> float:
    plate_v = p.width_mm * p.depth_mm * p.thickness_mm
    n = int(round(p.n_holes))
    hole_v = n * 3.14159265 * (p.hole_dia_mm / 2.0) ** 2 * p.thickness_mm
    return max(0.0, plate_v - hole_v)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.thickness_mm < _MIN_WALL_MM:
        out.append(f"thickness {p.thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    n = int(round(p.n_holes))
    if n > 0 and p.hole_dia_mm > 0 and (p.width_mm - 2 * p.margin_mm) < 0:
        out.append(f"margin_mm {p.margin_mm:.1f} mm too large for width_mm {p.width_mm:.1f} mm")
    return out


GLUE_TAB = register_subsystem(Subsystem(
    name="glue_tab",
    description="Small flat tab sized for a bonded joint -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("width_mm", value=15.0, min=5.0, max=60.0, unit='mm'),
        ParamSpec("depth_mm", value=10.0, min=3.0, max=40.0, unit='mm'),
        ParamSpec("thickness_mm", value=1.0, min=0.4, max=5.0, unit='mm'),
        ParamSpec("hole_dia_mm", value=2.0, min=1.0, max=5.0, unit='mm'),
        ParamSpec("n_holes", value=0, min=0, max=2, unit='count'),
        ParamSpec("margin_mm", value=3.0, min=1.0, max=10.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
