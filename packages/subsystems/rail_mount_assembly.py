"""Rail-mount assembly — a universal mounting rail with N subassembly plates bolted along it.

An assembly-template composite (`packages/subsystems/assembly_template.py`, the same live mechanism
`table.py` already uses): one "rail" child (a `flat_bar`) plus N "plate{i}" children (`mounting_plate_
grid`), evenly spaced along the rail and resting on top of it — real sibling `Instance`s in the
ledger tree, positioned by closed-form arithmetic computed ONCE here, never by the LLM hand-computing
coordinates.

Why this exists: a real electronics enclosure (a relay box, a control panel) is rarely just an empty
shell — it's a universal rail with plates bolted along it, each plate carrying its own board/module.
This gives that pattern as ONE addable catalog part instead of something the copilot has to assemble
from scratch out of a bare rail + loose plates.
"""

from __future__ import annotations

from packages.ledger.schema import Transform
from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import ChildSpec

_MIN_WALL_MM = 0.8

_FRAGMENT = """\
## Subsystem: Rail-mount assembly
An assembly — a **composition of parts**: a mounting rail with N subassembly plates bolted along it \
(the pattern a real electronics enclosure actually uses — a rail + plates, not an empty box). One \
high-level param block drives the whole thing:
- **rail_length_mm × rail_width_mm × rail_height_mm** — the rail's own cross-section and length.
- **plate_count** — how many subassembly plates sit along the rail (1-8).
- **plate_width_mm × plate_depth_mm × plate_thickness_mm** — each plate's own footprint/thickness.

### Intent mapping
- "longer rail" / "more room" → increase **rail_length_mm**.
- "more boards" / "more plates" → increase **plate_count**.
- "bigger plates" → increase **plate_width_mm**/**plate_depth_mm**.
- "sturdier rail" → increase **rail_height_mm**/**rail_width_mm**.\
"""


def _children(p) -> list[ChildSpec]:
    """Desired children: one "rail" `flat_bar` plus one "plate{i}" `mounting_plate_grid` per
    `plate_count`, evenly spaced along the rail's length and resting on its top face."""
    rail = ChildSpec(
        local_id="rail",
        subsystem_type="flat_bar",
        transform=Transform(z_mm=p.rail_height_mm / 2.0),
        params={
            "length_mm": p.rail_length_mm,
            "width_mm": p.rail_width_mm,
            "thickness_mm": p.rail_height_mm,
        },
    )
    n = int(round(p.plate_count))
    margin = p.plate_width_mm / 2.0
    usable = max(0.0, p.rail_length_mm - 2.0 * margin)
    spacing = usable / (n - 1) if n > 1 else 0.0
    plate_z = p.rail_height_mm + p.plate_thickness_mm / 2.0
    plates = [
        ChildSpec(
            local_id=f"plate{i}",
            subsystem_type="mounting_plate_grid",
            transform=Transform(x_mm=(-usable / 2.0 + i * spacing) if n > 1 else 0.0, z_mm=plate_z),
            params={
                "width_mm": p.plate_width_mm,
                "height_mm": p.plate_depth_mm,
                "thickness_mm": p.plate_thickness_mm,
            },
        )
        for i in range(n)
    ]
    return [rail, *plates]


def _check(p) -> list[str]:
    out: list[str] = []
    if p.plate_thickness_mm < _MIN_WALL_MM:
        out.append(f"plate_thickness {p.plate_thickness_mm:.2f} mm < min wall {_MIN_WALL_MM} mm")
    n = int(round(p.plate_count))
    if n > 1 and p.plate_width_mm * n > p.rail_length_mm:
        out.append(f"{n} plates at {p.plate_width_mm:.0f} mm wide overrun the "
                   f"{p.rail_length_mm:.0f} mm rail — grow the rail or shrink/reduce the plates")
    return out


RAIL_MOUNT_ASSEMBLY = register_subsystem(Subsystem(
    name="rail_mount_assembly",
    description="Mounting rail + N subassembly plates bolted along it (a composition of parts)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("rail_length_mm",     value=220.0, min=60.0,  max=500.0, unit="mm"),
        ParamSpec("rail_width_mm",      value=20.0,  min=8.0,   max=60.0,  unit="mm"),
        ParamSpec("rail_height_mm",     value=8.0,   min=3.0,   max=30.0,  unit="mm"),
        ParamSpec("plate_count",        value=2,     min=1,     max=8,     unit="count"),
        # 90x60 comfortably fits mounting_plate_grid's OWN default hole grid (4 cols x 3 rows at
        # 25mm pitch) without tripping ITS OWN "hole grid extends past plate edge" invariant.
        ParamSpec("plate_width_mm",     value=90.0,  min=40.0,  max=200.0, unit="mm"),
        ParamSpec("plate_depth_mm",     value=60.0,  min=40.0,  max=200.0, unit="mm"),
        ParamSpec("plate_thickness_mm", value=2.5,   min=0.8,   max=10.0,  unit="mm"),
    ],
    build=None,
    volume=None,
    invariants=_check,
    assembly_children=_children,
))
