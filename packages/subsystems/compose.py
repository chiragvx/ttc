"""Phase F — composition helpers (2026-07-03).

The "nesting principle" made ergonomic: a subsystem's `build` invokes other REGISTERED subsystems
and positions them into an assembly, without touching the ledger, the registry, or build123d
primitives directly. Every registered `Subsystem` is dual-use — usable standalone in the picker AND
callable from another subsystem's build with per-instance overrides. Phase F lands the four helpers
this makes possible:

- `call(name, **overrides)` → child TaggedPart from a registered subsystem's build (defaults + overrides)
- `place(part, x, y, z, rx, ry, rz)` → positioned/rotated child (rotations in degrees)
- `place_polar(part, radius, theta_deg, z)` → angular-array convenience (self-rotates to face outward)
- `compose({scope: part, ...})` → group solids into a Compound (no boolean fuse) + namespace tags
   (`hole[0].bore` under scope `leg[2]` becomes `leg[2].hole[0].bore` in the merged TaggedPart)

**Ledger stays flat.** The active subsystem's `params` (the user's knobs) drive the whole assembly —
hierarchy lives INSIDE `build`. Multi-instance ledger composition (each nested child as its own
`Instance` in the tree, per Phase G) is a separate surface, deferred until an interactive editor
demands it. For now: the parent subsystem's params are the single source of truth; the compose
helpers just orchestrate the geometry.

**Tags stay local, transforms accumulate as metadata.** A child's own tag data (`hole[0].bore =
{center: [12, 0], dia: 6}`) describes the child's LOCAL frame — matching OCAF label semantics.
`place` doesn't rewrite tag positions; it records the applied transform under `_placement` so
downstream code (picker, HUD, feature-targeting) can compose local frames outward as needed.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from packages.ledger.parameter import ParameterDef
from packages.subsystems.base import Namespace

if TYPE_CHECKING:
    from packages.truth_plane.regen.templated import TaggedPart


def call(name: str, **overrides) -> "TaggedPart":
    """Invoke a REGISTERED subsystem's `build` with its ParamSpec defaults, then apply `overrides`.
    Unknown kwargs raise KeyError (typos must fail loudly)."""
    from packages.subsystems import get_subsystem_model
    sub = get_subsystem_model(name)
    if sub.build is None:
        raise ValueError(f"subsystem {name!r} has no build function")
    known = {spec.name for spec in sub.params}
    unknown = set(overrides) - known
    if unknown:
        raise KeyError(f"unknown params for {name!r}: {sorted(unknown)}. Known: {sorted(known)}")
    resolved: dict[str, ParameterDef] = {}
    for spec in sub.params:
        v = overrides.get(spec.name, spec.value)
        resolved[spec.name] = ParameterDef(value=float(v), unit=spec.unit, bounds=(spec.min, spec.max))
    return sub.build(Namespace(resolved))


def place(
    part: "TaggedPart",
    *,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    rx: float = 0.0,
    ry: float = 0.0,
    rz: float = 0.0,
) -> "TaggedPart":
    """Position + rotate a TaggedPart. Rotations are in DEGREES about the world axes; applied
    before translation (rotate about the child's local origin, then translate). Returns a NEW
    TaggedPart — tag data is copied unchanged (still in the child's local frame); the applied
    transform is recorded under `_placement` for downstream inspection."""
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    solid = part.solid
    if rx or ry or rz:
        solid = bd.Rotation(rx, ry, rz) * solid
    if x or y or z:
        solid = bd.Pos(x, y, z) * solid
    tags = dict(part.tags)
    tags["_placement"] = {"kind": "transform", "translate": [x, y, z], "rotate_deg": [rx, ry, rz]}
    return TaggedPart(solid=solid, tags=tags)


def place_polar(
    part: "TaggedPart",
    *,
    radius: float,
    theta_deg: float,
    z: float = 0.0,
    face_out: bool = True,
) -> "TaggedPart":
    """Place a part at (r cos θ, r sin θ, z). When `face_out` (default), the part is also rotated
    by θ about Z so its local +X points radially outward — the natural pose for blades on a disc,
    spokes on a hub, standoffs on a ring."""
    theta = math.radians(theta_deg)
    return place(part, x=radius * math.cos(theta), y=radius * math.sin(theta), z=z,
                 rz=theta_deg if face_out else 0.0)


def corner_ring_positions(count: int, half_x: float, half_y: float) -> list[tuple[float, float]]:
    """Distribute N points: 4 corners first (or a subset for N<4), extras spread evenly along the
    two LONG sides (the "table legs" pattern — a central point absorbs one odd leftover). Shared by
    every subsystem that needs an evenly-distributed ring of supports/fasteners/legs around a
    rectangular footprint (`table.py`, `standoff_frame.py`)."""
    n = max(2, int(count))
    corners = [(-half_x, -half_y), (half_x, -half_y), (-half_x, half_y), (half_x, half_y)]
    if n <= 4:
        return corners[:n]
    positions = list(corners)
    extras = n - 4
    per_side = extras // 2
    for i in range(per_side):
        frac = (i + 1) / (per_side + 1)
        x = -half_x + frac * (2 * half_x)
        positions.append((x, -half_y))
        positions.append((x, +half_y))
    if extras % 2:
        positions.append((0.0, 0.0))  # a central support for odd extras
    return positions


def compose(scope_map: dict[str, "TaggedPart"]) -> "TaggedPart":
    """Group N positioned children into ONE TaggedPart, WITHOUT fusing them. Solids are gathered
    into a build123d `Compound` (`bd.Compound(children=[...])`) rather than summed with `+` — a
    boolean union would silently fuse any two children that touch or overlap (e.g. a table leg's
    top face coincident with the tabletop's underside) into a single contiguous manifold body,
    erasing the parting boundary between what are meant to be independently fabricable parts. A
    `Compound` keeps every child a distinct solid (`result.solid.solids()` yields N bodies) while
    still supporting `.bounding_box()` and STEP/STL export like a single solid would. Tags are
    namespaced: `{scope_map["leg[0]"].tags["hole.bore"]}` -> `"leg[0].hole.bore"` in the merged
    result. `_placement` (from `place`) is preserved as `<scope>._placement`."""
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    if not scope_map:
        raise ValueError("compose() needs at least one child")
    tags: dict[str, dict] = {}
    for scope, tp in scope_map.items():
        for k, v in tp.tags.items():
            tags[f"{scope}.{k}" if k != "_placement" else f"{scope}._placement"] = v
    combined = bd.Compound(children=[tp.solid for tp in scope_map.values()])
    return TaggedPart(solid=combined, tags=tags)


def fuse(**scope_map: "TaggedPart") -> "TaggedPart":
    """Boolean-union 2+ already-PLACED TaggedParts into ONE genuinely fused solid — the INTENTIONAL
    counterpart to `compose()` above, doing the opposite thing on purpose.

    `compose()`'s docstring explains why it deliberately does NOT fuse: a boolean union would
    silently weld together any two children that happen to touch or overlap (a table leg's top face
    flush with the tabletop's underside), erasing the parting boundary between parts that are meant
    to stay independently fabricable. `fuse()` is for the OPPOSITE situation — children that are
    SUPPOSED to become one continuous printable/machinable body (a wing faired into a fuselage, a
    boss welded onto a bracket), where a single manifold result is the actual design intent, not an
    accident of two solids brushing against each other. Read `compose()`'s docstring before reaching
    for either one: picking the wrong helper either silently fuses parts that should stay separable,
    or silently leaves parts touching-but-distinct when a real structural union was intended.

    Real build123d boolean union (`solid_a + solid_b`, the same `+` operator `lofted_hull.py`'s
    `outer - cavity` sibling `-` performs for subtraction) — NOT `bd.Compound`. This REQUIRES the
    inputs to have a genuine, non-zero-measure 3D overlap (not just a coincident touching face) to
    produce a single valid manifold solid; callers are responsible for placing their parts (via
    `place()`) with real interpenetration before calling this, same expectation `winged_fuselage.py`
    documents for its own wing/fuselage placement.

    Tags are namespaced EXACTLY the way `compose()` does it (`scope.key`, with `_placement` ->
    `scope._placement`) — fusing the SOLIDS does not fuse the TAGS; each input's tag data still
    describes its own local frame, and the merged result keeps every input's tag data addressable
    under its own scope name, same as a `compose()`d result. Unlike `compose()` (a positional
    scope-keyed dict, since its typical caller is looping over an arbitrary-length array of
    same-shaped children like table legs), `fuse()` takes its parts as KEYWORD arguments — its
    typical caller has a small, fixed number of semantically-distinct named parts (e.g.
    `fuse(fuselage=fuselage_part, wing=wing_part)`), so keyword names double as meaningful scope
    labels without a separate dict literal at the call site."""
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart
    if len(scope_map) < 2:
        raise ValueError("fuse() needs at least 2 parts to union")
    tags: dict[str, dict] = {}
    for scope, tp in scope_map.items():
        for k, v in tp.tags.items():
            tags[f"{scope}.{k}" if k != "_placement" else f"{scope}._placement"] = v
    parts = list(scope_map.values())
    fused = parts[0].solid
    for tp in parts[1:]:
        fused = fused + tp.solid
    return TaggedPart(solid=fused, tags=tags)
