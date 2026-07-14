"""Pickable feature list (`packages/subsystems/features.py`).

Verifies `list_pickable_features` at the pure-Python level: single-instance world offsets are the
identity, multi-instance offsets actually get applied, tags with no "center" (whole-body) and
"_placement" (positioning metadata) never leak into the returned list, and a subsystem with no
`geometry_builder` is skipped without crashing the whole listing.
"""

from __future__ import annotations

import dataclasses
import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, add_instance, get_subsystem
from packages.subsystems.assembly import instance_world_offsets
from packages.subsystems.features import list_pickable_features

HAS_B123D = importlib.util.find_spec("build123d") is not None

pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")


def test_single_instance_bracket_features_match_local_centers(base_ledger, seeded):
    """Sole instance's world offset is (0,0,0), so each hole[i].bore's returned point must equal its
    stored local center exactly (padded with z=0.0)."""
    led = seeded(base_ledger, "bracket")
    bare = get_subsystem("bracket").geometry_builder(led, led.root_id)
    expected_holes = {
        tag: meta for tag, meta in bare.tags.items()
        if tag != "_placement" and "center" in meta
    }
    assert expected_holes  # sanity: bracket really does have hole[i].bore tags

    features = list_pickable_features(led)
    assert len(features) == len(expected_holes)
    by_tag = {f["tag"]: f for f in features}
    assert set(by_tag) == set(expected_holes)
    for tag, meta in expected_holes.items():
        cx, cy = meta["center"][0], meta["center"][1]
        entry = by_tag[tag]
        assert entry["instance_id"] == led.root_id
        assert entry["point"] == [cx, cy, 0.0]
        assert entry["meta"] == meta


def test_two_instance_ledger_panel_features_get_world_offset(base_ledger, seeded):
    """A non-root `panel` child's hole[i].bore points are offset by panel1's own
    instance_world_offsets() translation -- NOT equal to the tag's raw local center."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "panel", "panel1", parent_id=led.root_id)

    offsets = instance_world_offsets(led)
    ox, oy, oz = offsets["panel1"]
    assert (ox, oy, oz) != (0.0, 0.0, 0.0)  # auto-laid-out, must actually move

    bare_panel = get_subsystem("panel").geometry_builder(led, "panel1")
    local_holes = {
        tag: meta for tag, meta in bare_panel.tags.items()
        if tag != "_placement" and "center" in meta
    }
    assert local_holes  # sanity: panel really does have hole[i].bore tags

    features = list_pickable_features(led)
    panel_features = {f["tag"]: f for f in features if f["instance_id"] == "panel1"}
    assert set(panel_features) == set(local_holes)
    for tag, meta in local_holes.items():
        cx, cy = meta["center"][0], meta["center"][1]
        local_point = [cx, cy, 0.0]
        expected_point = [cx + ox, cy + oy, 0.0 + oz]
        entry = panel_features[tag]
        assert entry["point"] == expected_point
        assert entry["point"] != local_point  # proves the world offset was actually applied


def test_center_less_tags_are_excluded(base_ledger, seeded):
    """A tag with no "center" key (bracket's own "plate.body") never appears in the list."""
    led = seeded(base_ledger, "bracket")
    features = list_pickable_features(led)
    tags = {f["tag"] for f in features}
    assert "plate.body" not in tags


def test_assembly_template_instance_and_children_produce_no_bogus_features(base_ledger, seeded):
    """`standoff_frame` migrated (2026-07-03) onto the assembly-template mechanism
    (`packages/subsystems/assembly_template.py`): it no longer builds fused Phase F geometry with an
    internal "_placement" tag to exclude -- its `geometry_builder` is `None` (see
    standoff_frame.py's `build=None`), so `add_instance` materializes it PLUS its real children
    (`frame1_base`, `frame1_standoff0..3`) as separate `Instance`s in the tree (via
    `reconcile_children`). Neither the featureless parent NOR its real children should leak any
    pickable feature: the parent has no geometry at all, and `flat_bar`/`standoff` tags carry no
    "center" key (whole-body tags), so both legitimately contribute zero features -- without
    breaking the rest of the listing."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "standoff_frame", "frame1", parent_id=led.root_id)

    # sanity: standoff_frame really is an assembly-template instance now (no geometry of its own),
    # and its real children were actually materialized.
    assert get_subsystem("standoff_frame").geometry_builder(led, "frame1") is None
    frame_child_ids = {"frame1_base", "frame1_standoff0", "frame1_standoff1",
                        "frame1_standoff2", "frame1_standoff3"}
    assert frame_child_ids <= set(led.instances)

    features = list_pickable_features(led)
    frame_related_tags = {f["tag"] for f in features
                           if f["instance_id"] in frame_child_ids | {"frame1"}}
    assert frame_related_tags == set()

    # root's own bracket features must still be present -- the featureless composite instance and
    # its children don't take down the whole listing.
    root_tags = {f["tag"] for f in features if f["instance_id"] == led.root_id}
    assert root_tags


def test_instance_with_no_geometry_builder_is_skipped(base_ledger, seeded, monkeypatch):
    """An instance whose subsystem has geometry_builder=None is skipped without crashing the whole
    listing -- other instances' features still return."""
    led = seeded(base_ledger, "bracket")
    led = add_instance(led, "standoff", "standoff1", parent_id=led.root_id)

    broken_ctx = dataclasses.replace(get_subsystem("standoff"), geometry_builder=None)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, "standoff", broken_ctx)

    features = list_pickable_features(led)
    assert not any(f["instance_id"] == "standoff1" for f in features)
    assert any(f["instance_id"] == led.root_id for f in features)
