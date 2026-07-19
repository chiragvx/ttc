"""Longeron — a long straight structural rail, a fuselage/wing spanwise member.

2026-07-16 — the FDM min-wall floor here now covers BOTH cross-section dimensions (`width_mm` and
`height_mm`), not just `height_mm`: this is a genuine rectangular cross-section, either dimension can
be the thin one depending on how a request sizes it, and the prior single-dimension check let a
too-thin `width_mm` through unflagged. Also registers `min_wall_params` on the Subsystem so
`packages/truth_plane/analysis.py::_min_wall_ok`'s FEA-time floor check (which normally finds a
subsystem's thin dimension via the `*_thickness_mm` naming convention) actually sees this part's real
wall-governing dimensions instead of silently no-oping (longeron has no `*_thickness_mm`-named param
at all, so the convention previously found nothing and the check always passed regardless of how thin
the part actually was)."""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_FRAGMENT = """\
## Subsystem: Longeron
A long straight structural rail — a fuselage/wing spanwise member (FDM/FFF or CNC). Same solid
rectangular-bar shape family as a flat bar, but sized for the much longer spans between bulkheads
or ribs that an airframe runs.
- **length_mm × width_mm × height_mm** — cross-section (width × height) extruded along length.

### Intent mapping
- "a 400mm fuselage section" → length_mm=400; "a full 1.2m wing spar" → length_mm=1200.
- "stiffer"/"less deflection" → increase **height_mm** (bending stiffness scales with height³) or
  **width_mm**; "lighter" → reduce the cross-section, watch the span-to-thickness ratio between
  supporting bulkheads/ribs.\
"""

_MIN_WALL_MM = 0.8  # FDM min-wall floor, packages/ledger/apply.py::MIN_WALL_MM


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    body = bd.Box(p.length_mm, p.width_mm, p.height_mm)
    return TaggedPart(body, {"longeron.body": {"kind": "solid",
                                               "size": [p.length_mm, p.width_mm, p.height_mm]}})


def _volume(p):
    return p.length_mm * p.width_mm * p.height_mm


def _check(p):
    violations = []
    if p.width_mm < _MIN_WALL_MM:
        violations.append(f"width {p.width_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.height_mm < _MIN_WALL_MM:
        violations.append(f"height {p.height_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    return violations


LONGERON = register_subsystem(Subsystem(
    name="longeron",
    description="Long straight structural rail — a fuselage/wing spanwise member (FDM/FFF or CNC)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm", value=400.0, min=50.0, max=1500.0, unit="mm"),
        ParamSpec("width_mm",  value=20.0,  min=5.0,  max=100.0,  unit="mm"),
        ParamSpec("height_mm", value=10.0,  min=0.8,  max=50.0,   unit="mm"),
    ],
    build=_build, volume=_volume, invariants=_check,
    fea_eligible=True,  # single Box, span along X — the validated cantilever methodology applies as-is
    min_wall_params=("width_mm", "height_mm"),  # no *_thickness_mm param — see module docstring
))
