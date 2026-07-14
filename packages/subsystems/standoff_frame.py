"""Standoff frame — an assembly-template subsystem (migrated 2026-07-03): a plate + N standoffs on
top, each a REAL sibling `Instance` in the ledger tree (not fused Phase F geometry).

Originally the first composite-of-registered-parts subsystem in the catalog (base plate as a fused
`flat_bar` + N fused `standoff` posts via `call()`/`compose()`). Migrated onto the assembly-template
mechanism (`packages/subsystems/assembly_template.py`): `assembly_children` returns the desired
`ChildSpec` list from the master's resolved params, and `reconcile_children` materializes them as
real child instances (`<root>_base`, `<root>_standoff0`, ...). This subsystem now has NO geometry of
its own (`build=None`, `volume=None`) — its children carry the real solids and mass; the master
params exist purely to derive the children's params + placement.

Positioning follows the same "4 corners + extras evenly along the long sides" pattern as
`render_table`, so a `standoff_count` of 6 puts standoffs at the 4 corners + 1 midpoint on each
long side; 8 adds 2 midpoints per long side; etc. Soft-bound like table's leg_count — the copilot
picks whatever count the user asks for (14 is fine; a physical invariant catches only the "no
room" case).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import ChildSpec

if TYPE_CHECKING:
    from packages.subsystems.base import Namespace

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Standoff frame (assembly)
An assembly — a **composition of parts**: a rectangular base plate carrying N standoffs on top.
Every standoff is identical (same OD / bore / height). Distribution: 4 corners, extras spread
evenly along the two long sides — same rule as the table's legs.

Parameters (all drive the whole assembly through one flat block):
- **plate_width_mm × plate_depth_mm × plate_thickness_mm** — the base plate.
- **standoff_outer_dia_mm × standoff_bore_mm × standoff_height_mm** — every standoff.
- **standoff_inset_mm** — how far each standoff is set in from the plate edges.
- **standoff_count** — how many standoffs (typical 4; extras distribute along the long sides).

### Intent mapping
- "more standoffs" / "6 posts" → set **standoff_count**.
- "M4 screws through" → **standoff_bore_mm** ≈ 4.5; "M3" → 3.4.
- "taller frame" → increase **standoff_height_mm**; "thicker base" → **plate_thickness_mm**.
- "posts closer to the corners" → decrease **standoff_inset_mm**.\
"""


def _children(p: "Namespace") -> list[ChildSpec]:
    """The desired child instances: one `flat_bar` base plate (centered at the origin, matching the
    old `_build`'s untouched `call("flat_bar", ...)` placement — no `place()` was ever applied to
    it) plus one `standoff` per post, positioned by the SAME corner-ring math the old fused `_build`
    used (kept verbatim — the bug being fixed is the fusion, not the placement)."""
    from packages.ledger.schema import Transform
    from packages.subsystems.compose import corner_ring_positions

    children = [
        ChildSpec(
            local_id="base",
            subsystem_type="flat_bar",
            transform=Transform(),
            params={
                "length_mm": p.plate_width_mm,
                "width_mm": p.plate_depth_mm,
                "thickness_mm": p.plate_thickness_mm,
            },
        )
    ]
    ox = p.plate_width_mm / 2.0 - p.standoff_inset_mm
    oy = p.plate_depth_mm / 2.0 - p.standoff_inset_mm
    stand_z = p.plate_thickness_mm / 2.0 + p.standoff_height_mm / 2.0
    for i, (x, y) in enumerate(corner_ring_positions(int(p.standoff_count), ox, oy)):
        children.append(ChildSpec(
            local_id=f"standoff{i}",
            subsystem_type="standoff",
            transform=Transform(x_mm=x, y_mm=y, z_mm=stand_z),
            params={
                "outer_dia_mm": p.standoff_outer_dia_mm,
                "inner_dia_mm": p.standoff_bore_mm,
                "height_mm": p.standoff_height_mm,
            },
        ))
    return children


def _check(p) -> list[str]:
    out: list[str] = []
    if p.plate_thickness_mm < _MIN_WALL_MM:
        out.append(f"plate_thickness {p.plate_thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if p.standoff_bore_mm >= p.standoff_outer_dia_mm:
        out.append(f"standoff bore {p.standoff_bore_mm:.1f} mm ≥ outer {p.standoff_outer_dia_mm:.1f} mm (no wall)")
    wall = (p.standoff_outer_dia_mm - p.standoff_bore_mm) / 2.0
    if wall < _MIN_WALL_MM:
        out.append(f"standoff wall {wall:.2f} mm < min wall {_MIN_WALL_MM} mm")
    # geometry sanity: standoffs must fit on the plate with the given inset
    if 2 * p.standoff_inset_mm + p.standoff_outer_dia_mm >= min(p.plate_width_mm, p.plate_depth_mm):
        out.append(f"standoff_inset {p.standoff_inset_mm:.0f} mm + standoff_outer_dia overruns the plate")
    return out


STANDOFF_FRAME = register_subsystem(Subsystem(
    name="standoff_frame",
    description="Base plate + N standoffs (assembly-template — flat_bar + standoff children)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("plate_width_mm",       value=100.0, min=40.0, max=400.0, unit="mm"),
        ParamSpec("plate_depth_mm",       value=80.0,  min=40.0, max=300.0, unit="mm"),
        ParamSpec("plate_thickness_mm",   value=3.0,   min=0.8,  max=20.0,  unit="mm"),
        ParamSpec("standoff_outer_dia_mm", value=10.0, min=4.0,  max=40.0,  unit="mm"),
        ParamSpec("standoff_bore_mm",      value=4.0,  min=1.0,  max=30.0,  unit="mm"),
        ParamSpec("standoff_height_mm",    value=15.0, min=3.0,  max=80.0,  unit="mm"),
        ParamSpec("standoff_inset_mm",     value=10.0, min=2.0,  max=80.0,  unit="mm"),
        ParamSpec("standoff_count",        value=4,    min=2,    max=12,    unit="count"),
    ],
    # No geometry of its own: children (base + standoffN) carry the real solids/mass. build=None
    # means the SubsystemContext's geometry_builder resolves to None (see register_subsystem's
    # `_build` closure) and volume=None means volume_mm3 resolves to 0.0 — both required so the
    # multi-instance telemetry/render paths (packages/transport/app.py::_telemetry/_render_geometry)
    # sum the CHILDREN's real geometry/mass instead of double-counting a stale analytic estimate here.
    build=None,
    volume=None,
    invariants=_check,
    assembly_children=_children,
))
