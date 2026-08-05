"""Press Fit Boss -- Boss with a slightly-undersized pilot for a press-fit metal insert

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
1) -- a cylinder with a concentric through-bore, the SAME shape family `standoff.py`
already registers (`render_standoff`), reused here under this part's own name/proportions per this
catalog's established "one archetype, many named catalog entries" convention (see `standoff.py`/
`washer.py`: washer already reuses the standoff generator the same way).
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import FitSocketSpec, cylinder_end_interfaces

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Press Fit Boss
Boss with a slightly-undersized pilot for a press-fit metal insert -- a cylindrical body with a concentric through-bore (FDM/FFF or turned).
- **outer_dia_mm** -- outer diameter.
- **inner_dia_mm** -- bore diameter.
- **height_mm** -- length along the axis.

### Intent mapping
- "for an M3 screw" -> inner_dia_mm ~= 3.4 (clearance); "M4" -> 4.5.
- "taller" / "longer" -> increase height_mm.
- "thicker wall" / "stronger" -> increase outer_dia_mm (wall = (outer - inner)/2, >= 0.8 mm).\
"""


def _build(p):
    from packages.truth_plane.regen.templated import render_standoff
    return render_standoff(outer_dia_mm=p.outer_dia_mm, inner_dia_mm=p.inner_dia_mm, height_mm=p.height_mm)


def _volume(p) -> float:
    ro, ri = p.outer_dia_mm / 2.0, p.inner_dia_mm / 2.0
    return math.pi * max(0.0, ro * ro - ri * ri) * p.height_mm


def _check(p) -> list[str]:
    if p.inner_dia_mm >= p.outer_dia_mm:
        return [f"inner_dia {p.inner_dia_mm:.1f} mm >= outer_dia {p.outer_dia_mm:.1f} mm (no wall)"]
    wall = (p.outer_dia_mm - p.inner_dia_mm) / 2.0
    if wall < _MIN_WALL_MM:
        return [f"wall {wall:.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


PRESS_FIT_BOSS = register_subsystem(Subsystem(
    name="press_fit_boss",
    description="Boss with a slightly-undersized pilot for a press-fit metal insert -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("outer_dia_mm", value=10.0, min=4.0, max=30.0, unit='mm'),
        ParamSpec("inner_dia_mm", value=4.0, min=1.0, max=25.0, unit='mm'),
        ParamSpec("height_mm", value=10.0, min=3.0, max=35.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    interfaces=cylinder_end_interfaces("height_mm"),  # 2026-07-27
    # 2026-08-04 (DFM fit expansion) — CONNECTOR side: `inner_dia_mm` is this boss's through-bore,
    # same shape family (`render_standoff`) and same param names as `spar_joiner_sleeve`/`box_sleeve`'s
    # own already-established `inner_dia_mm` fit_socket — a bore that receives `host_dia + clearance_mm`.
    # Note the sign: `FitBinding.clearance_mm` is explicitly documented as signed (packages/ledger/
    # schema.py: "positive = clearance/slip fit, negative = interference/press fit") — for THIS part's
    # own stated purpose ("a slightly-undersized pilot for a press-fit metal insert", see docstring
    # above), a caller wiring this fit is expected to pass a small NEGATIVE clearance_mm so the bore
    # comes out slightly under the insert's nominal OD, not the positive slip-fit clearance a plain
    # screw-clearance bore would use. compute_fit() itself is agnostic to the sign (packages/subsystems/
    # fit.py:107) — the interference-vs-clearance choice is the caller's, made at wire time.
    fit_socket=FitSocketSpec(kind="round", dim_params={"dia_mm": "inner_dia_mm"}),
))
