"""Leftover-volume geometry helper (2026-08-04, regions research follow-on).

This is a PLAIN GEOMETRY HELPER FUNCTION, not a ledger-persisted mechanism — contrast
`packages/ledger/schema.py::Region`, which IS ledger-persisted (a named keep-out/keep-in box, wired via
`packages/ledger/deltas.py::RegionOp`). This module never reads or writes `ledger.regions`; it exists
to help a HUMAN or the LLM pick reasonable `Region` box bounds, by showing what 3D space is actually
left over once an enclosure's interior has real components placed in it — a "here's what's free"
visualization/measurement aid, not a second source of truth.

Sourced from build-plan/research03aug/regions/purpose_tagged_regions_research.md (the regions prior-
art research this follows on from):

- **Geometry** — boolean subtract (`cavity - Fuse(components)`) is the real, documented mechanism
  (OCCT `BRepAlgoAPI_Cut` under build123d's `Mode.SUBTRACT`/`-` operator — confirmed via direct fetch
  of https://build123d.readthedocs.io/en/latest/key_concepts_builder.html, quoted in that doc). The
  doc's own sourced caveat (OCCT wiki, https://github.com/Open-Cascade-SAS/OCCT/wiki/boolean_operations):
  the Cut tool argument "should not be self-interfered, i.e. all sub-shapes... that have geometrical
  coincidence... must share these entities" — i.e. a raw `Compound` of mutually-touching/overlapping
  component solids (independently authored, positionally coincident but not topologically shared —
  e.g. two brackets flush against the same enclosure wall) can misbehave as a Cut argument. This module
  therefore ALWAYS fuses the components into ONE clean tool solid first (`Mode.ADD`/`+`, OCCT
  `BRepAlgoAPI_Fuse`), then subtracts that single fused solid from the cavity — never a raw multi-solid
  Compound passed straight into Cut, exactly the recipe the research doc's own "bottom line" section 1
  spells out.
- **Tagging** — build123d's `Shape.label` is a REAL, confirmed, persistent per-solid string attribute
  (same doc, directly quoting https://build123d.readthedocs.io/en/latest/assemblies.html: "In order
  [to] keep track of objects one can assign a `label` to all Shape objects... Labels are just strings
  with no further limitations"). Each disjoint solid the Cut result decomposes into
  (`result.solids()` — the same accessor `packages/subsystems/compose.py::compose`'s own docstring
  cites for "a Compound keeps every child a distinct solid") gets its `.label` set here — nothing in
  this module classifies a chunk as "routing_allowed" vs. "reserved" on its own; that judgment call
  stays with the caller (a human, or the LLM via a real `Region.label`), matching the research doc's
  own verdict that no domain-agnostic classification standard exists to build on top of, only the
  generic label/name primitive itself.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence


def leftover_volume(
    cavity,
    component_solids: Sequence,
    *,
    label_fn: Optional[Callable[[int, object], str]] = None,
) -> list:
    """`cavity - Fuse(component_solids)`, returning the list of disjoint leftover-space Solids, each
    with its `.label` already set.

    `cavity` / `component_solids` are real build123d `Shape`s (typically a `Solid` from `bd.Box(...)`/
    a subsystem's own geometry builder) already living in a SHARED coordinate frame — this function
    does no placement/transform of its own (contrast `packages.subsystems.assembly.
    instance_world_offsets`, which resolves world placement for real ledger instances; a caller
    building `component_solids` from placed instances should already have moved them into that shared
    frame — e.g. via `bd.Pos(...) * solid` — before calling this).

    Components are fused into ONE tool solid first (`+`, `BRepAlgoAPI_Fuse`) — per this module's own
    docstring on the sourced OCCT non-self-interference caveat — rather than ever building a raw
    `Compound` of the components and cutting with that directly. A single component skips the fuse
    loop entirely (nothing to union yet); zero components skips the Cut entirely (the whole cavity is
    "leftover" — Cutting an empty tool would either error or be a no-op depending on the kernel build,
    so this is handled explicitly rather than relying on that).

    `label_fn(i, solid)` (default: `f"leftover_{i}"`) names each disjoint chunk, `i` in `.solids()`
    order — build123d/OCCT topological order, NOT spatial sorting; a caller that wants to identify a
    SPECIFIC chunk (e.g. "the one near the back-left corner") should classify by that chunk's own
    `.bounding_box()`/`.center()`, not by index alone.

    Returns a plain `list` of build123d `Solid`s (already `.label`-tagged) — not a `Region` and not a
    ledger write of any kind; see this module's own docstring."""
    label_fn = label_fn or (lambda i, _solid: f"leftover_{i}")

    if component_solids:
        tool = component_solids[0]
        for solid in component_solids[1:]:
            tool = tool + solid  # Mode.ADD / BRepAlgoAPI_Fuse -- fuse BEFORE cutting, see module docstring
        remainder = cavity - tool  # Mode.SUBTRACT / BRepAlgoAPI_Cut
    else:
        remainder = cavity

    solids = list(remainder.solids())
    for i, s in enumerate(solids):
        s.label = label_fn(i, s)
    return solids
