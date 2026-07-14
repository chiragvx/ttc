"""Phase F composition helpers — call / place / place_polar / compose.

Verifies the four helpers work at the pure-Python level AND that the first composite-of-registered-
parts subsystem (`standoff_frame`) renders end to end: registered, positive volume, invariants
clean at defaults, geometry builds with expected root tag, telemetry positive.
"""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import (
    SUBSYSTEM_MODELS,
    SUBSYSTEM_REGISTRY,
    call,
    compose,
    get_subsystem,
    place,
    place_polar,
)

HAS_B123D = importlib.util.find_spec("build123d") is not None


# ------- call() -------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_call_defaults_produces_a_tagged_part():
    """No overrides — the child uses its ParamSpec defaults; every registered subsystem's build
    is exercisable via call() with zero arguments."""
    tp = call("standoff")
    assert tp.solid is not None
    assert "body.cyl" in tp.tag_keys and "bore.thru" in tp.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_call_applies_overrides():
    tp = call("standoff", outer_dia_mm=20.0, inner_dia_mm=6.0, height_mm=30.0)
    assert tp.tags["body.cyl"]["dia"] == 20.0
    assert tp.tags["body.cyl"]["height"] == 30.0
    assert tp.tags["bore.thru"]["dia"] == 6.0


def test_call_unknown_subsystem_raises_keyerror():
    with pytest.raises(KeyError):
        call("does_not_exist")


def test_call_unknown_param_raises_keyerror():
    with pytest.raises(KeyError):
        call("standoff", height_mm=15.0, misspelled_param=1.0)


# ------- place() -------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_place_records_transform_metadata():
    tp = call("standoff")
    moved = place(tp, x=25.0, y=-10.0, z=7.5, rz=45.0)
    p = moved.tags["_placement"]
    assert p["translate"] == [25.0, -10.0, 7.5]
    assert p["rotate_deg"] == [0.0, 0.0, 45.0]
    # tag DATA is preserved as-is (local frame)
    assert moved.tags["body.cyl"]["dia"] == tp.tags["body.cyl"]["dia"]


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_place_actually_translates_the_solid():
    """The placed solid's bounding-box center should shift by the applied translation."""
    tp = call("standoff", outer_dia_mm=10.0, inner_dia_mm=4.0, height_mm=10.0)
    bb0 = tp.solid.bounding_box().center()
    moved = place(tp, x=50.0, y=0.0, z=0.0)
    bb1 = moved.solid.bounding_box().center()
    assert abs(bb1.X - bb0.X - 50.0) < 1e-6


# ------- place_polar() -------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_place_polar_puts_the_part_on_the_ring():
    r = 40.0
    tp = call("standoff", outer_dia_mm=8.0, inner_dia_mm=2.0, height_mm=8.0)
    placed = place_polar(tp, radius=r, theta_deg=90.0)
    p = placed.tags["_placement"]
    # x = r cos 90 = 0; y = r sin 90 = r
    assert abs(p["translate"][0]) < 1e-6
    assert abs(p["translate"][1] - r) < 1e-6
    assert p["rotate_deg"] == [0.0, 0.0, 90.0]  # face_out default rotates by theta


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_place_polar_face_out_false_leaves_orientation():
    tp = call("standoff")
    placed = place_polar(tp, radius=25.0, theta_deg=60.0, face_out=False)
    assert placed.tags["_placement"]["rotate_deg"] == [0.0, 0.0, 0.0]


# ------- compose() -------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_compose_namespaces_tags_and_unions_solids():
    a = call("standoff", outer_dia_mm=6.0, inner_dia_mm=1.0, height_mm=5.0)
    b = place(call("standoff", outer_dia_mm=6.0, inner_dia_mm=1.0, height_mm=5.0), x=20.0)
    merged = compose({"leg[0]": a, "leg[1]": b})
    # child tags land under their scope prefix
    assert "leg[0].body.cyl" in merged.tag_keys
    assert "leg[1].body.cyl" in merged.tag_keys
    # placement metadata is preserved under the scope prefix too
    assert "leg[1]._placement" in merged.tag_keys


def test_compose_rejects_empty():
    with pytest.raises(ValueError):
        compose({})


# ------- standoff_frame (migrated to the assembly-template mechanism, 2026-07-03) -------
#
# `standoff_frame` no longer builds fused Phase F geometry — its `assembly_children` (see
# `packages/subsystems/standoff_frame.py::_children`) declares one `flat_bar` base + N `standoff`
# posts, materialized as REAL sibling `Instance`s in the ledger tree by `reconcile_children`. This
# file's `seeded`/`seeded_with` fixtures (tests/subsystems/conftest.py) predate the assembly-template
# mechanism and only seed the ROOT instance's params — `_seeded_frame()` below explicitly calls
# `reconcile_children` afterward, exactly like `packages/subsystems/__init__.py::add_instance` and
# `packages/ledger/apply.py::apply_instance_op` do for every other assembly-template call site. The root
# instance itself now has no geometry (`build=None`, `volume=None` — see standoff_frame.py's module
# docstring on why that's required to avoid double-counting mass against its children).

from packages.subsystems.assembly_template import reconcile_children


def _seeded_frame(base_ledger, seeded_with, **overrides):
    """`seeded()`/`seeded_with()` only seed the ROOT instance's params — they predate the
    assembly-template mechanism and don't know to reconcile children. Explicitly reconcile after
    seeding, exactly like `packages/subsystems/__init__.py::add_instance` and
    `packages/ledger/apply.py::apply_instance_op` do for every other assembly-template call site."""
    led = seeded_with(base_ledger, "standoff_frame", **overrides)
    return reconcile_children(led, led.root_id)


def test_standoff_frame_registered():
    assert "standoff_frame" in SUBSYSTEM_REGISTRY
    assert "standoff_frame" in SUBSYSTEM_MODELS
    sub = get_subsystem("standoff_frame")
    assert sub.name == "standoff_frame"
    assert "structures" in sub.applicable_disciplines


def test_standoff_frame_reconcile_creates_base_and_four_standoffs(base_ledger, seeded_with):
    led = _seeded_frame(base_ledger, seeded_with)
    root_id = led.root_id
    assert f"{root_id}_base" in led.instances
    for i in range(4):
        assert f"{root_id}_standoff{i}" in led.instances
    base = led.instances[f"{root_id}_base"]
    assert base.subsystem_type == "flat_bar"
    assert base.params["length_mm"].value == 100.0
    assert base.params["width_mm"].value == 80.0
    assert base.params["thickness_mm"].value == 3.0
    standoff0 = led.instances[f"{root_id}_standoff0"]
    assert standoff0.subsystem_type == "standoff"
    assert standoff0.params["outer_dia_mm"].value == 10.0
    assert standoff0.params["inner_dia_mm"].value == 4.0
    assert standoff0.params["height_mm"].value == 15.0
    # corner placement: inset 10mm from a 100x80 plate -> half-extents (40, 30); z lifts the
    # standoff to sit on top of the (centered) base plate: 3/2 + 15/2 = 9.0
    assert abs(standoff0.transform.x_mm) == pytest.approx(40.0)
    assert abs(standoff0.transform.y_mm) == pytest.approx(30.0)
    assert standoff0.transform.z_mm == pytest.approx(9.0)


def test_standoff_frame_volume_is_sum_of_children(base_ledger, seeded_with):
    led = _seeded_frame(base_ledger, seeded_with)
    root_id = led.root_id
    total = 0.0
    for iid, inst in led.instances.items():
        sub = get_subsystem(inst.subsystem_type)
        if sub.volume_mm3 is not None:
            total += sub.volume_mm3(led, iid)
    # base plate (100×80×3 = 24 000) + 4 standoffs each ~13.8 mm² wall area · 15 mm ≈ 207 mm³ each
    assert total > 24_000.0
    # the root itself must contribute NOTHING (build=None/volume=None) — real geometry lives on
    # the children only, so summing per-instance volume never double-counts.
    assert get_subsystem("standoff_frame").volume_mm3(led, root_id) == 0.0

    # sanity: total volume scales with standoff_count
    led8 = _seeded_frame(base_ledger, seeded_with, standoff_count=(8, 2, 12, "count"))
    total8 = sum(
        get_subsystem(inst.subsystem_type).volume_mm3(led8, iid)
        for iid, inst in led8.instances.items()
        if get_subsystem(inst.subsystem_type).volume_mm3 is not None
    )
    assert total8 > total  # more standoffs -> more mass


def test_standoff_frame_invariants_clean_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "standoff_frame")
    assert get_subsystem("standoff_frame").check_invariants(led) == []


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_standoff_frame_renders_as_five_distinct_solids(base_ledger, seeded_with):
    """The whole point of the migration: standoffs are real sibling instances, not geometry fused
    into the base plate. `render_assembly` composes the root + its 4 default children into one
    scene WITHOUT a boolean union — proven by 5 independently-countable solids (1 base + 4
    standoffs), matching `tests/subsystems/test_assembly.py::test_render_assembly_composes_two_instances`'s
    disjoint-solid-count pattern."""
    from packages.subsystems.assembly import render_assembly

    led = _seeded_frame(base_ledger, seeded_with)
    part = render_assembly(led)
    assert part.solid is not None
    solids = list(part.solid.solids())
    assert len(solids) == 5


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_standoff_frame_leg_count_change_reflects_in_geometry(base_ledger, seeded_with):
    """Bumping standoff_count past the recommended max still reconciles (soft bounds) and produces
    that many DISTINCT child instances/solids — the assembly-template path is parametric all the
    way through, not just tag names inside one fused part."""
    from packages.subsystems.assembly import render_assembly

    led = _seeded_frame(base_ledger, seeded_with, standoff_count=(8, 2, 12, "count"))
    root_id = led.root_id
    for i in range(8):
        assert f"{root_id}_standoff{i}" in led.instances

    part = render_assembly(led)
    solids = list(part.solid.solids())
    assert len(solids) == 9  # 1 base + 8 standoffs
