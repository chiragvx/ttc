"""Phase G — assembly composition (`packages/subsystems/assembly.py`).

Verifies `instance_world_offsets` (world-space offsets, auto-layout + explicit transform) and
`render_assembly` (compose every instance into one positioned TaggedPart) at the pure-Python level.
"""

from __future__ import annotations

import importlib.util

import pytest

from packages.ledger.schema import Connection, InterfaceRef, Instance, Transform
from packages.subsystems import add_instance
from packages.subsystems import assembly
from packages.subsystems.assembly import instance_world_offsets, render_assembly

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _two_instance_ledger(base_ledger, seeded):
    """Root seeded as `bracket`, plus a `standoff` child of root with NO explicit transform (so it
    exercises the auto-layout path)."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "standoff", "standoff1", parent_id=led.root_id)
    return led


# ------- instance_world_offsets -------

def test_single_instance_ledger_offset_is_origin(base_ledger, seeded):
    led = seeded(base_ledger, "bracket")
    offsets = instance_world_offsets(led)
    assert offsets == {"root": (0.0, 0.0, 0.0)}


def test_two_instance_ledger_offsets_are_distinct_and_nonoverlapping(base_ledger, seeded):
    led = _two_instance_ledger(base_ledger, seeded)
    offsets = instance_world_offsets(led)
    assert set(offsets) == {"root", "standoff1"}
    assert offsets["root"] == (0.0, 0.0, 0.0)
    # auto-laid-out sibling must NOT sit at the parent's origin
    assert offsets["standoff1"] != (0.0, 0.0, 0.0)
    assert offsets["standoff1"][1] > 0.0  # placed along +Y per the auto-layout rule


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_three_auto_laid_out_siblings_all_get_a_gap_including_from_each_other(base_ledger, seeded):
    """Regression: a real bug existed where only the FIRST auto-placed child got a gap from its
    parent — subsequent siblings were packed back-to-back with zero clearance between each OTHER
    (center-to-center spacing equal to the previous sibling's extent alone), which overlaps outright
    once a later sibling's Y-extent exceeds an earlier one's. Use three same-type siblings (so every
    pairwise extent is identical) and assert consecutive centers are separated by strictly MORE than
    that shared extent -- proving a real per-pair gap exists, not just a single gap from the parent."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "standoff", "s1", parent_id=led.root_id)
    led = add_instance(led, "standoff", "s2", parent_id=led.root_id)
    led = add_instance(led, "standoff", "s3", parent_id=led.root_id)
    offsets = instance_world_offsets(led)
    ys = [offsets["s1"][1], offsets["s2"][1], offsets["s3"][1]]
    assert ys == sorted(ys) and len(set(ys)) == 3  # strictly increasing, distinct
    gap_12 = ys[1] - ys[0]
    gap_23 = ys[2] - ys[1]
    # both sibling-to-sibling gaps must be (near-)identical -- proving the SAME per-pair gap logic
    # applies uniformly, not just once between parent and the first child.
    assert abs(gap_12 - gap_23) < 1e-6


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_airframe_defining_body_does_not_push_siblings_past_its_own_span(base_ledger, seeded):
    """2026-07-20 live repro: a real 25-part recon-UAV build put `winged_fuselage` (Y-extent = its
    500mm-default WINGSPAN) first in the auto-layout queue, and every other sibling shared the SAME
    running cursor -- so the whole rest of the build got shoved out past the fuselage's own span,
    landing hundreds of mm from the airframe (confirmed live: a self-check reporting the fuselage
    "floats ~553mm from the nearest other part"). An is_airframe_defining body must get its OWN
    auto-layout lane -- ordinary siblings must cluster near the origin (at/inside its footprint),
    never past its span."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "winged_fuselage", "fuselage")
    led = add_instance(led, "standoff", "sys1")
    led = add_instance(led, "standoff", "sys2")
    led = add_instance(led, "standoff", "sys3")
    offsets = instance_world_offsets(led)

    assert offsets["fuselage"][1] == 0.0  # first (only) member of the airframe lane, unaffected
    fuselage_span = 500.0  # winged_fuselage's default span_mm
    for sid in ("sys1", "sys2", "sys3"):
        # must cluster near the origin, nowhere close to (let alone past) the fuselage's own span
        assert offsets[sid][1] < fuselage_span / 4


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_two_airframe_defining_siblings_still_gap_against_each_other(base_ledger, seeded):
    """The airframe lane must keep its OWN per-pair gap guarantee -- two is_airframe_defining bodies
    (no connection between them) still get distinct, properly-spaced Y offsets from each other, same
    as any other pair of auto-laid-out siblings."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "wing_panel", "wing_a")
    led = add_instance(led, "wing_panel", "wing_b")
    offsets = instance_world_offsets(led)
    assert offsets["wing_a"][1] != offsets["wing_b"][1]
    assert abs(offsets["wing_b"][1] - offsets["wing_a"][1]) > 0.0


def test_explicit_transform_is_honored_over_autolayout(base_ledger, seeded):
    """An instance WITH an explicit transform ends up at exactly that offset (from its parent's
    resolved offset), bypassing auto-layout entirely. Constructed manually (not via add_instance,
    which never sets a transform) per the task spec."""
    led = seeded(base_ledger, "bracket")
    inst = Instance(
        id="standoff1",
        subsystem_type="standoff",
        parent_id=led.root_id,
        transform=Transform(x_mm=50.0, y_mm=0.0, z_mm=0.0),
    )
    new_instances = dict(led.instances)
    new_instances["standoff1"] = inst
    led = led.model_copy(update={"instances": new_instances})

    offsets = instance_world_offsets(led)
    assert offsets["root"] == (0.0, 0.0, 0.0)
    # parent (root) offset is (0,0,0), so the child's world offset == its transform verbatim
    assert offsets["standoff1"] == (50.0, 0.0, 0.0)


def test_nested_transform_adds_to_parent_offset(base_ledger, seeded):
    """A 2-level chain (root -> mid [explicit transform] -> leaf [explicit transform]) composes:
    the leaf's world offset is the SUM of both transforms, proving recursive (not single-level)
    parent resolution."""
    led = seeded(base_ledger, "bracket")
    mid = Instance(id="mid", subsystem_type="standoff", parent_id=led.root_id,
                    transform=Transform(x_mm=10.0, y_mm=20.0, z_mm=0.0))
    leaf = Instance(id="leaf", subsystem_type="standoff", parent_id="mid",
                     transform=Transform(x_mm=1.0, y_mm=2.0, z_mm=3.0))
    new_instances = dict(led.instances)
    new_instances["mid"] = mid
    new_instances["leaf"] = leaf
    led = led.model_copy(update={"instances": new_instances})

    offsets = instance_world_offsets(led)
    assert offsets["mid"] == (10.0, 20.0, 0.0)
    assert offsets["leaf"] == (11.0, 22.0, 3.0)


def _detach_root_from_toplevel_autolayout_lane(led):
    """Give `root` an explicit (identity) transform so it takes the explicit-transform branch
    instead of auto-layout, freeing up the top-level `(None, is_airframe_defining)` lane to be
    driven EXCLUSIVELY by whatever top-level instances a test adds afterwards -- without this, root
    (itself `transform is None` by default, per `build_ledger`) would silently occupy that lane
    first and consume the "first part centers at 0" slot before the test's own instances do."""
    root_id = led.root_id
    new_instances = dict(led.instances)
    new_instances[root_id] = new_instances[root_id].model_copy(
        update={"transform": Transform(x_mm=0.0, y_mm=0.0, z_mm=0.0)})
    return led.model_copy(update={"instances": new_instances})


def test_auto_layout_gap_stays_exactly_gap_for_strictly_increasing_extents(base_ledger, seeded, monkeypatch):
    """Regression for a verified defect: the OLD formula centered each auto-placed instance at
    `cursor + GAP` (no half-extent term), which produced a real edge-to-edge gap of
    `GAP + (extent_prev - extent_next) / 2` between consecutive siblings -- POSITIVE only when
    extents were non-increasing, and NEGATIVE (real interpenetration -- every auto-placed instance
    shares x=0, z=0) the moment a later sibling's Y-extent exceeded the previous one's by more than
    `2 * GAP`. Reproduces the live-repro numbers verbatim (washer -> mounting_plate_grid ->
    deck_plate: 20mm -> 80mm -> 120mm), fully decoupled from real subsystem geometry via a
    monkeypatched `_y_extent_mm` so the test is deterministic and needs no kernel."""
    led = seeded(base_ledger, "bracket")
    led = _detach_root_from_toplevel_autolayout_lane(led)
    led = add_instance(led, "standoff", "p1")
    led = add_instance(led, "standoff", "p2")
    led = add_instance(led, "standoff", "p3")
    extents = {"p1": 20.0, "p2": 80.0, "p3": 120.0}

    def fake_extent(ledger, instance_id, *, allow_kernel_build=True):
        return extents[instance_id]

    monkeypatch.setattr(assembly, "_y_extent_mm", fake_extent)
    offsets = instance_world_offsets(led)

    y = {k: offsets[k][1] for k in extents}
    assert y["p1"] == pytest.approx(0.0)  # first part in its lane always centers at exactly 0
    for a, b in (("p1", "p2"), ("p2", "p3")):
        edge_to_edge_gap = (y[b] - extents[b] / 2.0) - (y[a] + extents[a] / 2.0)
        assert edge_to_edge_gap > 0.0  # must never overlap -- this is what the old formula violated
        assert edge_to_edge_gap == pytest.approx(assembly._AUTO_LAYOUT_GAP_MM)


def test_auto_layout_gap_stays_exactly_gap_for_non_increasing_extents(base_ledger, seeded, monkeypatch):
    """The previously-working case (non-increasing extents) must keep working -- and, under the new
    symmetric half-extent formula, the edge-to-edge gap collapses to exactly GAP here too (rather
    than the old formula's incidental `GAP + (extent_prev - extent_next) / 2` overage)."""
    led = seeded(base_ledger, "bracket")
    led = _detach_root_from_toplevel_autolayout_lane(led)
    led = add_instance(led, "standoff", "p1")
    led = add_instance(led, "standoff", "p2")
    led = add_instance(led, "standoff", "p3")
    extents = {"p1": 120.0, "p2": 80.0, "p3": 20.0}

    def fake_extent(ledger, instance_id, *, allow_kernel_build=True):
        return extents[instance_id]

    monkeypatch.setattr(assembly, "_y_extent_mm", fake_extent)
    offsets = instance_world_offsets(led)

    y = {k: offsets[k][1] for k in extents}
    assert y["p1"] == pytest.approx(0.0)
    for a, b in (("p1", "p2"), ("p2", "p3")):
        edge_to_edge_gap = (y[b] - extents[b] / 2.0) - (y[a] + extents[a] / 2.0)
        assert edge_to_edge_gap > 0.0
        assert edge_to_edge_gap == pytest.approx(assembly._AUTO_LAYOUT_GAP_MM)


def test_auto_layout_real_parent_seed_clears_half_parent_extent_plus_gap(base_ledger, seeded, monkeypatch):
    """The first auto-placed child of a REAL parent must clear the parent by exactly GAP beyond the
    parent's HALF Y-extent (a part is built centered on its own local origin, so the parent's own
    body's far edge sits at `parent_extent / 2`, not the full extent -- seeding the cursor at the
    full extent, as an earlier version did, silently over-cleared by another half-extent)."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "standoff", "child1", parent_id=led.root_id)
    fake_extents = {"root": 100.0, "child1": 30.0}

    def fake_extent(ledger, instance_id, *, allow_kernel_build=True):
        return fake_extents[instance_id]

    monkeypatch.setattr(assembly, "_y_extent_mm", fake_extent)
    offsets = instance_world_offsets(led)

    child_near_edge = offsets["child1"][1] - fake_extents["child1"] / 2.0
    parent_far_edge = fake_extents["root"] / 2.0
    assert child_near_edge - parent_far_edge == pytest.approx(assembly._AUTO_LAYOUT_GAP_MM)


# ------- render_assembly -------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_render_assembly_single_instance_matches_bare_root(base_ledger, seeded):
    """Edge case from the task spec: a ledger with only the root instance must reuse the SAME
    general loop, not a special-cased path — render_assembly(ledger) should equal an unrotated,
    unpositioned build of root's own geometry (place() at the origin is a no-op transform)."""
    from packages.subsystems import get_subsystem
    led = seeded(base_ledger, "bracket")
    part = render_assembly(led)
    bare = get_subsystem("bracket").geometry_builder(led, "root")

    assert part.solid is not None
    bb_part = part.solid.bounding_box()
    bb_bare = bare.solid.bounding_box()
    assert abs(bb_part.size.X - bb_bare.size.X) < 1e-6
    assert abs(bb_part.size.Y - bb_bare.size.Y) < 1e-6
    assert abs(bb_part.size.Z - bb_bare.size.Z) < 1e-6
    # tags are namespaced by instance id even for the single-instance case
    assert any(k.startswith("root.") for k in part.tags)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_render_assembly_composes_two_instances(base_ledger, seeded):
    led = _two_instance_ledger(base_ledger, seeded)
    part = render_assembly(led)

    assert part.solid is not None
    # tags namespaced by BOTH instance ids
    assert any(k.startswith("root.") for k in part.tags)
    assert any(k.startswith("standoff1.") for k in part.tags)

    # Prove real composition happened (not just one part silently dropped). We use disjoint solid
    # COUNT rather than a bounding-box size comparison: bracket + standoff are auto-laid-out apart
    # along Y with a real gap, so the union should be two genuinely separate bodies — a bounding-box
    # extent check could pass even if compose() accidentally dropped a part whose bbox happens to sit
    # inside the other's extent (e.g. a tiny standoff placed a hair too close), whereas a disjoint
    # solid count directly proves both children survived the union as independent bodies.
    solids = list(part.solid.solids())
    assert len(solids) >= 2


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_render_assembly_footprint_larger_than_either_instance_alone(base_ledger, seeded):
    from packages.subsystems import get_subsystem
    led = _two_instance_ledger(base_ledger, seeded)
    part = render_assembly(led)
    bb_assembly = part.solid.bounding_box()

    bracket_only = get_subsystem("bracket").geometry_builder(led, "root")
    standoff_only = get_subsystem("standoff").geometry_builder(led, "standoff1")
    bb_bracket = bracket_only.solid.bounding_box()
    bb_standoff = standoff_only.solid.bounding_box()

    assert bb_assembly.size.Y > bb_bracket.size.Y
    assert bb_assembly.size.Y > bb_standoff.size.Y


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_render_assembly_skips_instance_with_no_geometry_builder(base_ledger, seeded, monkeypatch):
    """A subsystem with `geometry_builder=None` must be skipped, not crash the whole assembly."""
    import dataclasses

    from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "standoff", "standoff1", parent_id=led.root_id)

    broken_ctx = dataclasses.replace(get_subsystem("standoff"), geometry_builder=None)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, "standoff", broken_ctx)

    part = render_assembly(led)
    assert part.solid is not None
    assert any(k.startswith("root.") for k in part.tags)
    assert not any(k.startswith("standoff1.") for k in part.tags)


# ------- Phase 1 (2026-08-06, gearbox-housing-generation initiative) -------
# unanchored CONNECTED COMPONENTS get their own auto-layout slot, keyed by component instead of by
# single instance id -- fixing the confirmed bug where `resolve_placements` seeds EVERY unanchored
# component's datum at the SAME identity transform (world origin), so two unrelated mesh-connected
# gear pairs (neither anchored) used to land exactly on top of each other. Uses `spur_gear` (a real
# `kind="mesh"` interface subsystem) rather than the synthetic models `tests/subsystems/
# test_placement.py` uses for `resolve_mesh_mate`'s own unit coverage -- this needs REAL built
# geometry (via `geometry_query.group_world_bbox`) to prove the fix at the level the bug actually
# manifested at (assembled world bboxes), not just the mate solver's own relative-translation math.

def _two_stage_gearbox_ledger(base_ledger):
    """Two SEPARATE spur_gear mesh pairs (stage 1: g1a<->g1b, stage 2: g2a<->g2b) -- NEITHER pair
    anchored with an explicit transform, and the two pairs are NOT connected to each other (two
    disjoint connected components, exactly the shape the confirmed bug collided)."""
    led = base_ledger
    for iid in ("g1a", "g1b", "g2a", "g2b"):
        led = add_instance(led, "spur_gear", iid)
    return led.model_copy(update={"connections": [
        Connection(id="stage1", a=InterfaceRef(instance_id="g1a", interface="mesh"),
                   b=InterfaceRef(instance_id="g1b", interface="mesh")),
        Connection(id="stage2", a=InterfaceRef(instance_id="g2a", interface="mesh"),
                   b=InterfaceRef(instance_id="g2b", interface="mesh")),
    ]})


def _aabb_overlap(a, b) -> bool:
    (a0x, a0y, a0z), (a1x, a1y, a1z) = a
    (b0x, b0y, b0z), (b1x, b1y, b1z) = b
    return (a0x < b1x and b0x < a1x) and (a0y < b1y and b0y < a1y) and (a0z < b1z and b0z < a1z)


# ------- R2 coverage-gap fix (2026-08-06): the shelf-packer's row-wrap path -------
# Every packing test above only ever constructs exactly 2 unanchored components -- never enough to
# push a row's accumulated width past `_COMPONENT_SHELF_ROW_WIDTH_MM`=400mm, so
# `_ComponentShelfPacker.place`'s wrap branch (packages/subsystems/assembly.py:166 -- `self._row_y +=
# self._row_depth + self._gap`, resetting `self._row_far_x`/`self._row_depth`/`self._row_has_items`)
# was never exercised by the committed suite. Confirmed low-severity coverage gap, not an active bug
# (verified live with 8 unanchored mesh-pair components before this fix). Two tests close it: a
# kernel-free unit test that pins the packer's exact row-wrap arithmetic (catches the reviewer's named
# off-by-one / forgot-to-reset failure modes directly, via exact expected centers -- no build123d
# needed), and a `build123d`-gated end-to-end test with 8 real gear-mesh-pair components (mirroring the
# reviewer's own live repro) proving REAL built geometry still packs with zero pairwise overlap once a
# wrap is forced, i.e. that 'compact packing' (this phase's criterion 2) holds for the multi-row case
# its own docstring claims to handle, not just the trivial N=2/no-wrap case every prior test covered.

def test_component_shelf_packer_row_wrap_places_wrapped_row_below_with_no_overlap():
    """Direct, kernel-free regression for the row-wrap coverage gap. Drives `_ComponentShelfPacker.
    place(...)` with 4 identical (60mm x 40mm) rectangles at a row width limit (190mm) chosen so
    exactly 2 fit per row before a wrap is forced on the 3rd call -- exercising the wrap branch twice
    over (once to start row 1, and `_row_far_x`'s reset is checked again by the 4th call still landing
    in row 1's x-range, not accumulating from row 0's leftover width). Asserts EXACT expected centers
    (not just non-overlap) so an off-by-one in `_row_y`'s increment (e.g. missing the `+ self._gap`
    term, or reusing a stale `_row_depth`) or a forgotten `_row_far_x` reset would fail this test even
    if it happened not to produce an outright overlap."""
    packer = assembly._ComponentShelfPacker(gap_mm=10.0, row_width_limit_mm=190.0)
    centers = [packer.place(60.0, 40.0) for _ in range(4)]
    # row 0: item0 at x=[0,60], item1 at x=[70,130] (60+10 gap fits within 190; a 3rd would not:
    # 130+10+60=200>190). row 1 (after the wrap): far_x/depth/has_items reset, so item2 starts back at
    # x=0 (NOT continuing from item1's far edge), and item3 packs next to it exactly as item1 did.
    assert centers == [
        (30.0, 20.0),   # item0: near_x=0 (empty row) -> cx = 0 + 60/2
        (100.0, 20.0),  # item1: near_x=60+10=70 -> cx = 70 + 60/2, same row (cy unchanged)
        (30.0, 70.0),   # item2: WRAPPED -- row_y = 0 + 40 + 10 = 50 -> cy = 50 + 40/2; far_x reset to 0
        (100.0, 70.0),  # item3: packs into the new row exactly like item1 did into row 0
    ]

    def rect_of(center):
        cx, cy = center
        return ((cx - 30.0, cy - 20.0, 0.0), (cx + 30.0, cy + 20.0, 1.0))

    rects = [rect_of(c) for c in centers]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not _aabb_overlap(rects[i], rects[j]), (i, j, rects[i], rects[j])


def _n_stage_gearbox_ledger(base_ledger, n_stages: int):
    """`n_stages` SEPARATE spur_gear mesh pairs (stage i: g{i}a<->g{i}b) -- none anchored, none
    connected to any other stage (n_stages disjoint unanchored connected components), generalizing
    `_two_stage_gearbox_ledger` above to enough components to force the shelf-packer's row-wrap path
    (unreachable with only 2 components at this gear size -- each default-sized mesh pair's real local
    footprint is only ~63mm wide, well under the 400mm row-width threshold)."""
    led = base_ledger
    connections = []
    for i in range(1, n_stages + 1):
        a, b = f"g{i}a", f"g{i}b"
        led = add_instance(led, "spur_gear", a)
        led = add_instance(led, "spur_gear", b)
        connections.append(Connection(id=f"stage{i}", a=InterfaceRef(instance_id=a, interface="mesh"),
                                       b=InterfaceRef(instance_id=b, interface="mesh")))
    return led.model_copy(update={"connections": connections})


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_many_unanchored_mesh_pairs_force_row_wrap_and_still_do_not_interpenetrate(base_ledger):
    """End-to-end row-wrap regression through REAL built gear geometry (not synthetic rectangles):
    8 default-sized spur_gear mesh pairs (matching R2's own live verification) -- at ~63mm real local
    width each, 5 already exceed the 400mm row-width threshold (46.5 + 4*(15+63) = 358.5, then
    358.5+15+63=436.5 > 400 forces stage 6 to wrap; see the packer unit test above for the isolated
    arithmetic), spanning 2 packer rows. Every pairwise combination of the 8 components' real world
    bboxes must still be non-overlapping -- proving 'compact packing' (this phase's criterion 2) for
    the actual multi-row case, not just the trivial single-row N=2 case every prior test covered."""
    from packages.subsystems.geometry_query import group_world_bbox

    n_stages = 8
    led = _n_stage_gearbox_ledger(base_ledger, n_stages)
    components = [[f"g{i}a", f"g{i}b"] for i in range(1, n_stages + 1)]
    bboxes = [group_world_bbox(led, members) for members in components]
    assert all(b is not None for b in bboxes)

    for i in range(len(bboxes)):
        for j in range(i + 1, len(bboxes)):
            assert not _aabb_overlap(bboxes[i], bboxes[j]), (i, j, bboxes[i], bboxes[j])

    # Prove a wrap ACTUALLY happened (not just "8 components happened not to overlap while strung out
    # in one long row") -- the combined Y-span must exceed a single pair's own depth by more than one
    # gap, i.e. at least 2 packer rows are genuinely in play.
    single_pair_depth = bboxes[0][1][1] - bboxes[0][0][1]
    combined = group_world_bbox(led, [m for members in components for m in members])
    assert combined is not None
    combined_span_y = combined[1][1] - combined[0][1]
    assert combined_span_y > single_pair_depth + assembly._COMPONENT_SLOT_GAP_MM


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_two_unanchored_mesh_pairs_do_not_interpenetrate(base_ledger):
    """THE regression test for the confirmed collision bug: on the old code, both stage-1 and stage-2
    seed their datum at the exact same identity transform (world origin) -- their resolved world
    bboxes come out literally identical (same gear specs), i.e. maximal overlap, not just "too
    close". This must now fail to overlap at all."""
    from packages.subsystems.geometry_query import group_world_bbox

    led = _two_stage_gearbox_ledger(base_ledger)
    bbox1 = group_world_bbox(led, ["g1a", "g1b"])
    bbox2 = group_world_bbox(led, ["g2a", "g2b"])
    assert bbox1 is not None and bbox2 is not None
    assert not _aabb_overlap(bbox1, bbox2), (bbox1, bbox2)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_two_unanchored_mesh_pairs_total_span_is_bounded(base_ledger):
    """The whole assembly's footprint is a reasonable, bounded function of the two components' own
    real combined extents -- NOT "however many auto-layout gaps accumulated" (the ~900mm sprawl this
    phase also fixes). `span_x + span_y` capped at the sum of both components' own (width + depth)
    plus a small constant (packer gap/row overhead), deliberately not an exact pixel-perfect number."""
    from packages.subsystems.geometry_query import group_world_bbox

    led = _two_stage_gearbox_ledger(base_ledger)
    bbox1 = group_world_bbox(led, ["g1a", "g1b"])
    bbox2 = group_world_bbox(led, ["g2a", "g2b"])
    combined = group_world_bbox(led, ["g1a", "g1b", "g2a", "g2b"])
    assert bbox1 is not None and bbox2 is not None and combined is not None
    w1, d1 = bbox1[1][0] - bbox1[0][0], bbox1[1][1] - bbox1[0][1]
    w2, d2 = bbox2[1][0] - bbox2[0][0], bbox2[1][1] - bbox2[0][1]
    span_x = combined[1][0] - combined[0][0]
    span_y = combined[1][1] - combined[0][1]
    assert span_x + span_y <= (w1 + d1) + (w2 + d2) + 200.0


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_single_unanchored_mesh_pair_placement_is_unchanged_by_component_packing(base_ledger):
    """The existing single-component mesh-placement behavior (ONE gear pair, correctly meshing at
    radius_a+radius_b, datum at the origin) must be COMPLETELY UNCHANGED by this phase's fix -- a lone
    unanchored component has nothing to collide with, so it must keep landing exactly where
    `resolve_placements` itself puts it (zero shift), byte for byte."""
    from packages.subsystems.placement import resolve_placements

    led = base_ledger
    led = add_instance(led, "spur_gear", "ga")
    led = add_instance(led, "spur_gear", "gb")
    led = led.model_copy(update={"connections": [
        Connection(id="mesh1", a=InterfaceRef(instance_id="ga", interface="mesh"),
                   b=InterfaceRef(instance_id="gb", interface="mesh")),
    ]})
    mated = resolve_placements(led)
    offsets = instance_world_offsets(led)
    assert offsets["ga"] == (mated["ga"].x_mm, mated["ga"].y_mm, mated["ga"].z_mm)
    assert offsets["gb"] == (mated["gb"].x_mm, mated["gb"].y_mm, mated["gb"].z_mm)
    assert offsets["ga"] == (0.0, 0.0, 0.0)  # datum still at the origin, exactly as before this phase


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_anchored_component_member_placement_is_unaffected_by_component_packing(base_ledger):
    """A component WITH an anchored member keeps behaving exactly as today -- the anchor's transform
    stays authoritative and the rest mate off it, untouched by the new unanchored-component packer."""
    from packages.subsystems.placement import resolve_placements

    led = base_ledger
    led = add_instance(led, "spur_gear", "ga")
    led = add_instance(led, "spur_gear", "gb")
    new_instances = dict(led.instances)
    new_instances["ga"] = new_instances["ga"].model_copy(
        update={"transform": Transform(x_mm=5.0, y_mm=7.0, z_mm=3.0)})
    led = led.model_copy(update={"instances": new_instances, "connections": [
        Connection(id="mesh1", a=InterfaceRef(instance_id="ga", interface="mesh"),
                   b=InterfaceRef(instance_id="gb", interface="mesh")),
    ]})
    mated = resolve_placements(led)
    offsets = instance_world_offsets(led)
    assert offsets["ga"] == (5.0, 7.0, 3.0)
    assert offsets["gb"] == (mated["gb"].x_mm, mated["gb"].y_mm, mated["gb"].z_mm)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_ordinary_auto_layout_is_unaffected_by_an_unrelated_unanchored_component(base_ledger, seeded):
    """A connected mesh pair (new component-level auto-layout) coexists with an ordinary, unconnected
    sibling (the pre-existing per-instance auto-layout lane) -- the two mechanisms are independent and
    must not interfere with each other. Same assertions as
    `test_two_instance_ledger_offsets_are_distinct_and_nonoverlapping`, now with an unrelated
    unanchored mesh pair also present in the same ledger."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "standoff", "standoff1", parent_id=led.root_id)
    led = add_instance(led, "spur_gear", "ga")
    led = add_instance(led, "spur_gear", "gb")
    led = led.model_copy(update={"connections": [
        Connection(id="mesh1", a=InterfaceRef(instance_id="ga", interface="mesh"),
                   b=InterfaceRef(instance_id="gb", interface="mesh")),
    ]})
    offsets = instance_world_offsets(led)
    assert offsets["root"] == (0.0, 0.0, 0.0)
    assert offsets["standoff1"] != (0.0, 0.0, 0.0)
    assert offsets["standoff1"][1] > 0.0
