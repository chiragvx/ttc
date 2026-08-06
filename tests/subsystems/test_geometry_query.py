"""geometry_query.py (`packages/subsystems/geometry_query.py`) — Phase 0 of the gearbox-housing-
generation initiative. Verifies the four shared query ops (`placed_solid`/`world_bbox`/
`group_world_bbox`/`group_convex_hull`) against a synthetic, hand-computed ledger, and confirms
graceful `None` on every failure mode the module commits to never raising over.

Uses `flat_bar` (a plain `bd.Box`, centered on its own local origin) rather than a cylindrical
primitive: every extent is exact, integer, hand-computable arithmetic (half of length/width/
thickness), AND — the part that actually matters for the hull-containment assertion below — a box's
flat faces tessellate to vertices that land EXACTLY on its analytic bounding box with zero curvature-
approximation slack (verified live: a tessellated `bd.Cylinder`'s radial extent comes in a hair under
its true analytic radius at any finite tessellation tolerance, which would make a strict
hull-bbox->=world-bbox assertion flaky for a round part)."""

from __future__ import annotations

import importlib.util

import pytest

from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Transform
from packages.subsystems import add_instance, get_subsystem
from packages.subsystems import geometry_query as gq

HAS_B123D = importlib.util.find_spec("build123d") is not None

pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")


def _pd(value: float) -> ParameterDef:
    return ParameterDef(value=value, unit="mm", bounds=(-1e6, 1e6))


def _set_bar_dims(led, instance_id: str, length: float, width: float, thickness: float):
    """Directly mutate an already-added flat_bar instance's dimension params to known values (wide-
    open bounds — bounds are advisory only, see packages/ledger/CLAUDE.md) so every bbox in this file
    is exact, hand-computable arithmetic, independent of flat_bar's own catalog defaults ever
    changing. Matches tests/backend/test_validate.py::_make's own direct-mutation convention —
    `MasterParametricLedger`/`Instance` are plain (non-frozen) pydantic models."""
    led.instances[instance_id].params["length_mm"] = _pd(length)
    led.instances[instance_id].params["width_mm"] = _pd(width)
    led.instances[instance_id].params["thickness_mm"] = _pd(thickness)


def _three_bar_ledger(base_ledger, seeded):
    """root: 40x20x10 flat_bar at the origin (single top-level instance, transform=None -> auto-
    layout seeds it at exactly Y=0, per assembly.py's own documented rule — see
    tests/subsystems/test_assembly.py::test_single_instance_ledger_offset_is_origin for the same
    invariant exercised directly). post2/post3: same subsystem, explicit non-overlapping Transforms,
    own known dims. Every bbox below is `(±length/2, ±width/2, ±thickness/2)` shifted by the
    instance's own transform — exact integer arithmetic, no OCCT round-off to account for."""
    led = seeded(base_ledger, "flat_bar")
    root_id = led.root_id
    _set_bar_dims(led, root_id, length=40.0, width=20.0, thickness=10.0)

    led = add_instance(led, "flat_bar", "post2")
    _set_bar_dims(led, "post2", length=30.0, width=10.0, thickness=8.0)
    led.instances["post2"].transform = Transform(x_mm=100.0, y_mm=0.0, z_mm=0.0)

    led = add_instance(led, "flat_bar", "post3")
    _set_bar_dims(led, "post3", length=20.0, width=20.0, thickness=20.0)
    led.instances["post3"].transform = Transform(x_mm=0.0, y_mm=80.0, z_mm=50.0)

    return led, root_id


# ------- world_bbox -------

def test_world_bbox_matches_hand_computation_for_the_root_instance(base_ledger, seeded):
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    bb = gq.world_bbox(led, root_id)
    assert bb == ((-20.0, -10.0, -5.0), (20.0, 10.0, 5.0))


def test_world_bbox_applies_the_instances_own_explicit_transform(base_ledger, seeded):
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    bb = gq.world_bbox(led, "post2")
    # 30x10x8 half-extents (15, 5, 4), translated by (100, 0, 0). Box faces are exact -- no
    # tessellation/round-off involved in world_bbox at all (it reads OCCT's own analytic
    # bounding_box()), so plain equality (not pytest.approx, which also can't nest tuples anyway).
    assert bb == ((85.0, -5.0, -4.0), (115.0, 5.0, 4.0))


def test_world_bbox_returns_none_for_an_unknown_instance_id(base_ledger, seeded):
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    assert gq.world_bbox(led, "does_not_exist") is None


def test_placed_solid_returns_none_when_kernel_build_is_disallowed(base_ledger, seeded):
    # allow_kernel_build=False (interactive-plane gate, Inversion #2) -- flat_bar has a real
    # geometry_builder, but nothing cheap/analytic is available here, so this must be None, never a
    # raise and never a silently-wrong fallback geometry.
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    assert gq.placed_solid(led, root_id, allow_kernel_build=False) is None
    assert gq.world_bbox(led, root_id, allow_kernel_build=False) is None


# ------- rotation (R2, Phase 0 review: no Transform in this file set rx_deg/ry_deg/rz_deg before this
# fix, so placed_solid's `bd.Rotation(rx, ry, rz) * solid` line was never executed by the suite -- a
# coverage gap, not a live bug: manually verified live before this fix that a 90 deg Z-rotated
# 40x20x10 flat_bar already produced the correct swapped-half-extent bbox. These tests use a
# translation with NONZERO components on every axis, not just the rotated one, specifically so a
# future rotate<->translate reordering bug is caught no matter which axis is rotated -- a translation
# purely along the rotation's own axis commutes with that rotation and would hide a reordering bug on
# that axis (verified live). -------

def test_world_bbox_applies_an_rz_rotation_before_the_translation(base_ledger, seeded):
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    led.instances["post2"].transform = Transform(x_mm=100.0, y_mm=50.0, z_mm=30.0, rz_deg=90.0)
    bb = gq.world_bbox(led, "post2")
    # post2 is 30x10x8 -> local half-extents (X=15, Y=5, Z=4). A 90 deg Z rotation swaps the X/Y
    # half-extents (-> X=5, Y=15, Z unchanged=4), THEN the result is translated by (100, 50, 30).
    # Verified live against build123d directly, both for this correct rotate-then-translate order and
    # for a deliberately-reordered translate-then-rotate variant, which produces a different bbox --
    # confirming this assertion would catch that specific reordering bug.
    assert bb == ((95.0, 35.0, 26.0), (105.0, 65.0, 34.0))


def test_world_bbox_applies_an_rx_rotation_before_the_translation(base_ledger, seeded):
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    led.instances["post2"].transform = Transform(x_mm=100.0, y_mm=50.0, z_mm=30.0, rx_deg=90.0)
    bb = gq.world_bbox(led, "post2")
    # A 90 deg X rotation swaps the Y/Z half-extents (X unchanged=15, Y=5<->Z=4 -> Y=4, Z=5), THEN
    # translated by (100, 50, 30). (An x-only translation would have commuted with this rotation and
    # hidden a reordering bug -- see the section comment above for why (100, 50, 30) is used instead.)
    assert bb == ((85.0, 46.0, 25.0), (115.0, 54.0, 35.0))


def test_world_bbox_applies_a_ry_rotation_before_the_translation(base_ledger, seeded):
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    led.instances["post2"].transform = Transform(x_mm=100.0, y_mm=50.0, z_mm=30.0, ry_deg=90.0)
    bb = gq.world_bbox(led, "post2")
    # A 90 deg Y rotation swaps the X/Z half-extents (X=15<->Z=4 -> X=4, Z=15, Y unchanged=5), THEN
    # translated by (100, 50, 30).
    assert bb == ((96.0, 45.0, 15.0), (104.0, 55.0, 45.0))


def test_world_bbox_handles_a_negative_rotation_angle_without_dropping_it(base_ledger, seeded):
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    led.instances["post2"].transform = Transform(x_mm=100.0, y_mm=50.0, z_mm=30.0, rz_deg=-90.0)
    bb = gq.world_bbox(led, "post2")
    # NOTE on what a bbox-only assertion can and can't prove for a box centered on its own local
    # origin: verified live that such a box's bounding box (and even its full rotated VERTEX set) is
    # IDENTICAL for +90 vs -90 deg -- rotating by 180 deg is always a no-op on a centered box, on any
    # axis, for any starting angle, so R(theta) and R(theta+180) always coincide for it; -90 = 90-180.
    # So this assertion alone can't tell a correctly-signed -90 deg rotation apart from a bug that
    # silently negated it back to +90 -- see the dedicated sign test below for the one check in this
    # file that can. What THIS test covers instead: that a negative angle actually reaches
    # `bd.Rotation` (rather than being dropped/clamped to 0 by an `if rx or ry or rz` off-by-
    # truthiness bug or similar, which would leave the un-rotated (85, 45, 26)-(115, 55, 34) box
    # instead).
    assert bb == ((95.0, 35.0, 26.0), (105.0, 65.0, 34.0))


def test_placed_solid_respects_the_sign_of_a_rotation_angle(base_ledger, seeded):
    """The one test in this file that can actually distinguish a correctly-signed rotation from a
    sign-flipped one -- the 90 deg tests above structurally can't (see the previous test's own
    docstring: any multiple of 90 deg is also a multiple of 180 deg away from its own negation modulo
    the box's own 180 deg self-symmetry, so +90 and -90 always coincide for a centered box). A 30 deg
    angle breaks that coincidence -- verified live that the rotated VERTEX SETS for +30 vs -30 deg are
    genuinely different, not just relabeled -- so this is the one place in the file that deliberately
    departs from the "exact integer, no trig" convention in the module docstring, specifically to
    close the sign blind spot."""
    import math

    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    led.instances["post2"].transform = Transform(x_mm=0.0, y_mm=0.0, z_mm=0.0, rz_deg=30.0)
    solid = gq.placed_solid(led, "post2")
    assert solid is not None

    # post2's local corner at (length/2, width/2, thickness/2) = (15, 5, 4). A standard CCW-about-+Z
    # rotation by +30 deg sends (x, y) -> (x*cos(theta) - y*sin(theta), x*sin(theta) + y*cos(theta));
    # `sign_flipped` is what that same source corner maps to under -30 deg instead -- what a
    # sign-flip bug would produce.
    theta = math.radians(30.0)
    expected = (
        15.0 * math.cos(theta) - 5.0 * math.sin(theta),
        15.0 * math.sin(theta) + 5.0 * math.cos(theta),
        4.0,
    )
    theta_neg = math.radians(-30.0)
    sign_flipped = (
        15.0 * math.cos(theta_neg) - 5.0 * math.sin(theta_neg),
        15.0 * math.sin(theta_neg) + 5.0 * math.cos(theta_neg),
        4.0,
    )
    vertices = [(v.X, v.Y, v.Z) for v in solid.vertices()]

    def _has(pt):
        return any(
            abs(vx - pt[0]) < 1e-6 and abs(vy - pt[1]) < 1e-6 and abs(vz - pt[2]) < 1e-6
            for vx, vy, vz in vertices
        )

    assert _has(expected)          # verified live: present when rz_deg=30 (correctly signed)
    assert not _has(sign_flipped)  # verified live: this is what rz_deg=-30 would produce instead


# ------- group_world_bbox -------

def test_group_world_bbox_is_the_union_of_two_nonoverlapping_instances(base_ledger, seeded):
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    gbb = gq.group_world_bbox(led, [root_id, "post2"])
    assert gbb == (
        (min(-20.0, 85.0), min(-10.0, -5.0), min(-5.0, -4.0)),
        (max(20.0, 115.0), max(10.0, 5.0), max(5.0, 4.0)),
    )
    assert gbb == ((-20.0, -10.0, -5.0), (115.0, 10.0, 5.0))


def test_group_world_bbox_over_three_instances_matches_hand_computed_union(base_ledger, seeded):
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    gbb = gq.group_world_bbox(led, [root_id, "post2", "post3"])
    assert gbb == ((-20.0, -10.0, -5.0), (115.0, 90.0, 60.0))


def test_group_world_bbox_skips_an_unbuildable_member_rather_than_failing_the_whole_group(base_ledger, seeded):
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    gbb = gq.group_world_bbox(led, [root_id, "does_not_exist"])
    assert gbb == gq.world_bbox(led, root_id)  # the one real member's own box, unaffected


def test_group_world_bbox_returns_none_when_every_member_fails(base_ledger, seeded):
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    assert gq.group_world_bbox(led, ["ghost_a", "ghost_b"]) is None
    assert gq.group_world_bbox(led, []) is None


# ------- group_convex_hull -------

def test_group_convex_hull_contains_the_group_bbox_and_has_positive_volume(base_ledger, seeded):
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    members = [root_id, "post2", "post3"]
    group_bbox = gq.group_world_bbox(led, members)

    hull = gq.group_convex_hull(led, members)
    assert hull is not None
    assert bool(hull.is_valid)
    assert hull.volume > 0.0

    hb = hull.bounding_box()
    hull_min = (hb.min.X, hb.min.Y, hb.min.Z)
    hull_max = (hb.max.X, hb.max.Y, hb.max.Z)
    # a hull must CONTAIN every member -- its own bbox is at least as large as the group's, on every
    # axis, both directions (flat_bar's box faces tessellate exactly, see the module docstring, so
    # this holds to float precision, not just approximately).
    for axis in range(3):
        assert hull_min[axis] <= group_bbox[0][axis] + 1e-6
        assert hull_max[axis] >= group_bbox[1][axis] - 1e-6


def test_group_convex_hull_returns_none_for_an_empty_group(base_ledger, seeded):
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    assert gq.group_convex_hull(led, []) is None


def test_group_convex_hull_returns_none_when_no_member_resolves_to_geometry(base_ledger, seeded):
    # every member fails to build -> zero points collected -> well under the 4-point floor a 3D hull
    # needs. Stands in for a literal "1-2 point" degenerate case (unreachable through the public API
    # with REAL geometry -- any single tessellated solid already contributes far more than 4 points;
    # see the module docstring's own note on this).
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    assert gq.group_convex_hull(led, ["ghost_a", "ghost_b"]) is None


def test_group_convex_hull_returns_none_when_kernel_build_is_disallowed(base_ledger, seeded):
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    assert gq.group_convex_hull(led, [root_id, "post2", "post3"], allow_kernel_build=False) is None


# ------- raw_build (the one function in this module that propagates a real build exception) -------

def test_raw_build_returns_none_for_the_same_non_error_outcomes_as_placed_solid(base_ledger, seeded):
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    assert gq.raw_build(led, "does_not_exist") is None
    assert gq.raw_build(led, root_id, allow_kernel_build=False) is None


def test_raw_build_returns_the_unplaced_local_solid(base_ledger, seeded):
    # UNPLACED: root sits at world (0,0,0) here anyway, so this alone doesn't prove no-placement, but
    # combined with placed_solid's own bbox test above (which DOES apply a translation for post2/
    # post3), the two together confirm raw_build skips rotate/translate while placed_solid applies it.
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    solid = gq.raw_build(led, root_id)
    assert solid is not None
    bb = solid.bounding_box()
    assert (bb.min.X, bb.min.Y, bb.min.Z) == pytest.approx((-20.0, -10.0, -5.0))


def test_raw_build_returns_none_for_an_assembly_template_master_whose_build_returns_none(base_ledger, seeded):
    # R2 (Phase 0 review): raw_build documents FOUR None-return conditions but only two (unknown
    # instance id, allow_kernel_build=False) were ever tested in this file. This test covers the
    # "build() returns None" condition using a REAL assembly-template MASTER node (standoff_frame,
    # registered with build=None -- see standoff_frame.py's own module docstring: "This subsystem now
    # has NO geometry of its own ... its children carry the real solids and mass"), not a synthetic
    # one. Verified live: `get_subsystem("standoff_frame").geometry_builder` is NOT None -- every
    # catalog subsystem goes through `register_subsystem` (packages/subsystems/__init__.py), which
    # always sets `geometry_builder` to its own `_build` closure, even for a `build=None` master --
    # `build=None` only makes CALLING that closure return None (`_build`'s
    # `sub.build(...) if sub.build else None`), which is raw_build's SEPARATE `part is None` line,
    # not its `builder is None` line. See the next test for that other, literal branch.
    led, _root_id = _three_bar_ledger(base_ledger, seeded)
    led = add_instance(led, "standoff_frame", "frame1")
    assert gq.raw_build(led, "frame1") is None
    # placed_solid/world_bbox both start from raw_build, so the same None propagates through them too.
    assert gq.placed_solid(led, "frame1") is None
    assert gq.world_bbox(led, "frame1") is None


def test_raw_build_returns_none_when_the_resolved_subsystem_has_no_geometry_builder(base_ledger, seeded, monkeypatch):
    # The other of raw_build's four documented None-return conditions R2 flagged as untested: the
    # literal `builder is None` line. No subsystem in today's catalog actually reaches it through
    # `get_subsystem` (see the previous test's docstring -- `register_subsystem` always sets a real
    # `_build` closure), so it's exercised directly here via a temporary registry swap -- the code
    # this module and raw_build's own docstring both commit to ("a subsystem whose geometry_builder is
    # None ... returns None") must still behave correctly (not e.g. raise an AttributeError) rather
    # than silently rot as untested dead code.
    import dataclasses

    from packages.subsystems import SUBSYSTEM_REGISTRY

    led, root_id = _three_bar_ledger(base_ledger, seeded)
    no_builder_ctx = dataclasses.replace(get_subsystem("flat_bar"), geometry_builder=None)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, "flat_bar", no_builder_ctx)
    assert gq.raw_build(led, root_id) is None
    assert gq.placed_solid(led, root_id) is None
    assert gq.world_bbox(led, root_id) is None


def test_group_world_bbox_skips_an_assembly_template_master_instance(base_ledger, seeded):
    # The realistic failure scenario R2 flagged: a group that includes an assembly-template MASTER
    # instance (raw_build/placed_solid/world_bbox all None for it, per the tests above) must not crash
    # group_world_bbox -- e.g. an AttributeError from mishandling that None -- but silently skip it,
    # exactly like any other unbuildable member
    # (test_group_world_bbox_skips_an_unbuildable_member_rather_than_failing_the_whole_group above),
    # leaving the group's box the real geometry-bearing member's own box.
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    led = add_instance(led, "standoff_frame", "frame1")
    gbb = gq.group_world_bbox(led, [root_id, "frame1"])
    assert gbb == gq.world_bbox(led, root_id)


def test_raw_build_propagates_a_real_build_exception_instead_of_swallowing_it(base_ledger, seeded):
    # The one behavior this module's docstring calls out as deliberate and load-bearing: unlike every
    # other function here (which logs + returns None on any failure), raw_build must let a genuine
    # `geometry_builder` raise propagate to its caller -- that's what lets validate.py::_placed tell a
    # truly broken part (a `degeneracy` error, ok=False) apart from a subsystem with no geometry at all
    # (silent skip). A negative dimension makes flat_bar's own `bd.Box(p.length_mm, ...)` call itself
    # raise (confirmed live: `bd.Box(-5, 10, 10)` raises `Standard_DomainError`, an OCP/OCCT exception,
    # not a pydantic/ValueError one -- ParameterDef bounds are advisory-only on a directly-mutated
    # ledger, see `_set_bar_dims`'s own docstring, so nothing upstream of `bd.Box` intercepts this
    # first). If a future edit wrapped raw_build's `builder(...)` call in a try/except -- e.g. copying
    # placed_solid's own swallow-everything pattern -- this test would start failing (no raise, no
    # exception to catch) instead of silently losing the distinction validate.py depends on.
    led, root_id = _three_bar_ledger(base_ledger, seeded)
    _set_bar_dims(led, root_id, length=-5.0, width=10.0, thickness=10.0)
    with pytest.raises(Exception):
        gq.raw_build(led, root_id)
