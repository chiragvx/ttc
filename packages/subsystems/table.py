"""Table subsystem — assembly-template composite (migrated 2026-07-03): flat_bar top + N
round_post legs, as REAL sibling `Instance`s in the ledger tree.

Supersedes the earlier Phase F `call`/`place`/`compose` approach (which fused the top and legs into
one `TaggedPart` via a boolean-safe `Compound`, but as ONE ledger instance) — that approach's
`_build` is gone. The table root instance now only declares `assembly_children`: it has no geometry
of its own (`build=None`, `volume=None`); `reconcile_children()` (see
`packages/subsystems/assembly_template.py`) materializes its children ("top" = a `flat_bar`, "leg0"
… "legN-1" = `round_post`s) as independently-addressable instances under it, so
`assembly.render_assembly()` composes them as genuinely separate solids — the fix for the original
"legs fused to the tabletop" bug, which was a fusion problem, not a positioning one.
"""

from __future__ import annotations

from packages.ledger.schema import Transform
from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import ChildSpec
from packages.subsystems.compose import corner_ring_positions

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Table (assembly)
An assembly — a **composition of parts**: a rectangular tabletop resting on N legs. One high-level
param block drives the whole thing:
- **top_width_mm × top_depth_mm × top_thickness_mm** — the tabletop plate.
- **leg_dia_mm** — leg (cylinder) diameter.
- **leg_height_mm** — how tall the table stands.
- **leg_inset_mm** — how far each leg is set in from the top's edges.
- **leg_count** — how many legs (2–12). 4 legs sit at the corners; extras are distributed evenly
  along the two long sides (e.g. 6 = 4 corners + 1 midpoint each side; 8 = 4 corners + 2 midpoints).

### Intent mapping
- "taller table" → increase **leg_height_mm**; "bigger top" → increase top_width/top_depth.
- "sturdier legs" → increase **leg_dia_mm**; "legs at the corners" → decrease **leg_inset_mm**.
- "8 legs" / "more legs for support" → set **leg_count** = 8 (or 6, 10, …).\
"""


def _children(p) -> list[ChildSpec]:
    """Desired children: one "top" `flat_bar` plus one "leg{i}" `round_post` per `leg_count`, at the
    exact positions the old fused `_build` used (that math was always correct — the bug was fusing
    them together, not where they sat)."""
    top = ChildSpec(
        local_id="top",
        subsystem_type="flat_bar",
        transform=Transform(z_mm=p.leg_height_mm + p.top_thickness_mm / 2.0),
        params={
            "length_mm": p.top_width_mm,
            "width_mm": p.top_depth_mm,
            "thickness_mm": p.top_thickness_mm,
        },
    )
    ox = p.top_width_mm / 2.0 - p.leg_inset_mm
    oy = p.top_depth_mm / 2.0 - p.leg_inset_mm
    legs = [
        ChildSpec(
            local_id=f"leg{i}",
            subsystem_type="round_post",
            transform=Transform(x_mm=x, y_mm=y, z_mm=p.leg_height_mm / 2.0),
            params={"dia_mm": p.leg_dia_mm, "height_mm": p.leg_height_mm},
        )
        for i, (x, y) in enumerate(corner_ring_positions(int(p.leg_count), ox, oy))
    ]
    return [top, *legs]


def _check(p) -> list[str]:
    out: list[str] = []
    if p.top_thickness_mm < _MIN_WALL_MM:
        out.append(f"top_thickness {p.top_thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    if 2 * p.leg_inset_mm + p.leg_dia_mm >= min(p.top_width_mm, p.top_depth_mm):
        out.append(f"leg_inset {p.leg_inset_mm:.0f} mm + leg_dia overruns the tabletop footprint")
    return out


TABLE = register_subsystem(Subsystem(
    name="table",
    description="Table assembly — a tabletop on four legs (a composition of parts)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("top_width_mm",     value=120.0, min=60.0, max=400.0, unit="mm"),
        ParamSpec("top_depth_mm",     value=80.0,  min=40.0, max=300.0, unit="mm"),
        ParamSpec("top_thickness_mm", value=8.0,   min=2.0,  max=25.0,  unit="mm"),
        ParamSpec("leg_dia_mm",       value=12.0,  min=4.0,  max=40.0,  unit="mm"),
        ParamSpec("leg_height_mm",    value=60.0,  min=20.0, max=300.0, unit="mm"),
        ParamSpec("leg_inset_mm",     value=12.0,  min=2.0,  max=80.0,  unit="mm"),
        ParamSpec("leg_count",        value=4,     min=2,    max=12,    unit="count"),
    ],
    build=None,
    volume=None,
    invariants=_check,
    assembly_children=_children,
))
