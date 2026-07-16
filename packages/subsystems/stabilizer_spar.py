"""Stabilizer Spar -- Structural beam for horizontal/vertical stabilizer

Structural/mounting geometry only (`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md` category
3) -- a solid rectangular bar, the SAME shape family `longeron.py`/`flat_bar.py` already
register, reused here under this part's own name/proportions per this catalog's established "one
archetype, many named catalog entries" convention. `fea_eligible` deliberately left at its default
False (`base.py`: "opt-in per subsystem, not inferred") even though the shape matches `longeron.py`'s
own -- that opt-in call is left to whoever explicitly reviews this specific part for it, not inferred
here from shape alone.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Stabilizer Spar
Structural beam for horizontal/vertical stabilizer -- a solid rectangular bar (FDM/FFF or CNC).
- **length_mm x width_mm x height_mm** -- cross-section (width x height) extruded along length.

### Intent mapping
- "longer" -> increase length_mm.
- "stiffer" / "less deflection" -> increase height_mm (bending stiffness scales with height cubed)
  or width_mm; "lighter" -> reduce the cross-section.\
"""


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Box(p.length_mm, p.width_mm, p.height_mm)
    return TaggedPart(body, {"body.solid": {"kind": "solid",
                                            "size": [p.length_mm, p.width_mm, p.height_mm]}})


def _volume(p) -> float:
    return p.length_mm * p.width_mm * p.height_mm


def _check(p) -> list[str]:
    if p.height_mm < _MIN_WALL_MM:
        return [f"height {p.height_mm:.2f} mm < min wall {_MIN_WALL_MM} mm"]
    return []


STABILIZER_SPAR = register_subsystem(Subsystem(
    name="stabilizer_spar",
    description="Structural beam for horizontal/vertical stabilizer -- structural/mounting geometry (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm", value=250.0, min=50.0, max=1000.0, unit='mm'),
        ParamSpec("width_mm", value=10.0, min=3.0, max=60.0, unit='mm'),
        ParamSpec("height_mm", value=6.0, min=2.0, max=30.0, unit='mm'),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
))
