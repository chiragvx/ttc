"""compute_envelope (`packages/subsystems/envelope.py`) — Phase 2 of the gearbox-housing-generation
initiative. Verifies the derived coarse-bbox/hull-bbox values against a synthetic, hand-computed
ledger, and confirms the ok=False ("unknown", must-block) paths for a missing housing, a housing whose
subsystem doesn't declare `envelope_socket`, an empty `wraps`, a dangling `wraps` member, an unknown
subsystem type, and a wraps group with no buildable geometry — mirroring
`tests/subsystems/test_geometry_query.py`'s own offline/synchronous style (no HTTP, no async, no LLM).

No subsystem in the catalog declares `envelope_socket` yet (Phase 2's own scope is additive, zero real
adopters until a later phase) — `housing_model` below monkeypatches a throwaway registry entry
(`SUBSYSTEM_MODELS["_test_housing"]`, a `flat_bar`-shaped model with `envelope_socket` set) purely so
this file can exercise BOTH `compute_envelope`'s "no envelope_socket" REJECTED branch (using ordinary
`flat_bar`) and its real ok=True path (using `_test_housing`) — the same technique
`test_geometry_query.py::test_raw_build_returns_none_when_the_resolved_subsystem_has_no_geometry_builder`
already uses for an analogous zero-adopter gap. The housing instance's OWN geometry is never BUILT by
`compute_envelope` (only its `wraps` MEMBERS are) — but the housing instance still has to be a REAL,
resolvable registry entry: `group_world_bbox` calls `instance_world_offsets`, which auto-layouts EVERY
instance in the ledger (not just the wraps members) and looks up each one's `is_airframe_defining` via
`get_subsystem(...)` (`packages/subsystems/assembly.py::_is_airframe_defining`) — so `housing_model`
below registers `_test_housing` into BOTH `SUBSYSTEM_MODELS` (what `compute_envelope`/`get_subsystem_model`
read) AND `SUBSYSTEM_REGISTRY` (what auto-layout's `get_subsystem` reads), reusing `flat_bar`'s own
already-real `geometry_builder`/`seed_defaults`/etc. so the housing instance is fully resolvable even
though this file never asserts anything about the housing's OWN geometry.
"""

from __future__ import annotations

import dataclasses
import importlib.util

import pytest

from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Transform
from packages.subsystems import SUBSYSTEM_MODELS, SUBSYSTEM_REGISTRY, add_instance, get_subsystem, get_subsystem_model
from packages.subsystems.base import EnvelopeSocketSpec
from packages.subsystems.envelope import EnvelopeComputeResult, compute_envelope, housing_alignment_transform

HAS_B123D = importlib.util.find_spec("build123d") is not None

pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")

_HOUSING_TYPE = "_test_housing"


def _pd(value: float) -> ParameterDef:
    return ParameterDef(value=value, unit="mm", bounds=(-1e6, 1e6))


def _set_bar_dims(led, instance_id: str, length: float, width: float, thickness: float):
    """Same direct-mutation convention as test_geometry_query.py::_set_bar_dims — bounds are
    advisory-only (packages/ledger/CLAUDE.md), and Instance/params are plain, non-frozen models."""
    led.instances[instance_id].params["length_mm"] = _pd(length)
    led.instances[instance_id].params["width_mm"] = _pd(width)
    led.instances[instance_id].params["thickness_mm"] = _pd(thickness)


@pytest.fixture
def housing_model(monkeypatch):
    """Registers a throwaway `_test_housing` Subsystem (a `flat_bar`-shaped copy with
    `envelope_socket` set) into BOTH `SUBSYSTEM_MODELS` and `SUBSYSTEM_REGISTRY` — reverted
    automatically by monkeypatch after each test, never pollutes the real catalog. See this module's
    own docstring for why the `SUBSYSTEM_REGISTRY` half is needed too (auto-layout resolves every
    ledger instance, including the housing itself, not just its wraps members)."""
    base_model = get_subsystem_model("flat_bar")
    housing = dataclasses.replace(
        base_model, name=_HOUSING_TYPE,
        envelope_socket=EnvelopeSocketSpec(dim_params={
            "hull_bbox_x_mm": "outer_width_mm",
            "hull_bbox_y_mm": "outer_depth_mm",
            "hull_bbox_z_mm": "outer_height_mm",
        }),
    )
    monkeypatch.setitem(SUBSYSTEM_MODELS, _HOUSING_TYPE, housing)
    housing_ctx = dataclasses.replace(get_subsystem("flat_bar"), name=_HOUSING_TYPE)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, _HOUSING_TYPE, housing_ctx)
    return housing


def _two_member_ledger(base_ledger, seeded):
    """root: 40x20x10 flat_bar at the origin (auto-layout seeds transform=None -> Y=0, per
    assembly.py's documented rule, same as test_geometry_query.py's own fixture). member2: 30x10x8
    flat_bar translated to (100, 0, 0). Every bbox below is exact, hand-computable integer arithmetic
    (half of length/width/thickness), no OCCT round-off — same rationale as
    test_geometry_query.py's own module docstring for choosing flat_bar over a curved primitive."""
    led = seeded(base_ledger, "flat_bar")
    root_id = led.root_id
    _set_bar_dims(led, root_id, length=40.0, width=20.0, thickness=10.0)

    led = add_instance(led, "flat_bar", "member2")
    _set_bar_dims(led, "member2", length=30.0, width=10.0, thickness=8.0)
    led.instances["member2"].transform = Transform(x_mm=100.0, y_mm=0.0, z_mm=0.0)

    return led, root_id


# ------- ok=True: hand-computed coarse bbox + hull bbox -------


def test_compute_envelope_matches_hand_computed_bbox_and_hull_extents(base_ledger, seeded, housing_model):
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = [root_id, "member2"]

    result = compute_envelope(led, "housing1")
    assert result.ok is True
    assert result.reason is None

    # root: half-extents (20, 10, 5) at the origin -> (-20,-10,-5)-(20,10,5).
    # member2: half-extents (15, 5, 4) translated by (100, 0, 0) -> (85,-5,-4)-(115,5,4).
    # Union: x [-20, 115] -> 135; y [-10, 10] -> 20; z [-5, 5] -> 10.
    assert result.values["coarse_bbox_x_mm"] == pytest.approx(135.0)
    assert result.values["coarse_bbox_y_mm"] == pytest.approx(20.0)
    assert result.values["coarse_bbox_z_mm"] == pytest.approx(10.0)

    # A convex hull's bounding box is ALWAYS identical to the bounding box of the point set it was
    # built from (taking a convex hull never moves a per-axis min/max) — and flat_bar's flat box faces
    # tessellate to vertices landing EXACTLY on its analytic bbox (test_geometry_query.py's own module
    # docstring), so for two axis-aligned boxes the hull's own bbox extents equal the coarse union's,
    # to float precision.
    assert result.values["hull_bbox_x_mm"] == pytest.approx(135.0, abs=1e-4)
    assert result.values["hull_bbox_y_mm"] == pytest.approx(20.0, abs=1e-4)
    assert result.values["hull_bbox_z_mm"] == pytest.approx(10.0, abs=1e-4)

    # 2026-08-06 R5 fix: the group's real world CENTER, not just its size — the coarse union bbox was
    # x [-20, 115], y [-10, 10], z [-5, 5], so its midpoint is (47.5, 0, 0).
    assert result.values["coarse_bbox_center_x_mm"] == pytest.approx(47.5)
    assert result.values["coarse_bbox_center_y_mm"] == pytest.approx(0.0)
    assert result.values["coarse_bbox_center_z_mm"] == pytest.approx(0.0)


def test_compute_envelope_over_a_single_member_matches_its_own_bbox(base_ledger, seeded, housing_model):
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = [root_id]

    result = compute_envelope(led, "housing1")
    assert result.ok is True
    assert result.values["coarse_bbox_x_mm"] == pytest.approx(40.0)
    assert result.values["coarse_bbox_y_mm"] == pytest.approx(20.0)
    assert result.values["coarse_bbox_z_mm"] == pytest.approx(10.0)
    assert result.values["hull_bbox_x_mm"] == pytest.approx(40.0, abs=1e-4)
    assert result.values["hull_bbox_y_mm"] == pytest.approx(20.0, abs=1e-4)
    assert result.values["hull_bbox_z_mm"] == pytest.approx(10.0, abs=1e-4)


# ------- ok=False: precise reasons -------


def test_compute_envelope_rejected_for_unknown_housing_instance(base_ledger, seeded):
    led, _root_id = _two_member_ledger(base_ledger, seeded)
    result = compute_envelope(led, "does_not_exist")
    assert result.ok is False
    assert result.values == {}
    assert "does_not_exist" in result.reason
    assert "does not exist" in result.reason


def test_compute_envelope_rejected_for_unknown_subsystem_type(base_ledger, seeded):
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, "flat_bar", "housing1")
    led.instances["housing1"].subsystem_type = "totally_unregistered_subsystem_type"
    led.instances["housing1"].wraps = [root_id, "member2"]

    result = compute_envelope(led, "housing1")
    assert result.ok is False
    assert "totally_unregistered_subsystem_type" in result.reason


def test_compute_envelope_rejected_when_subsystem_declares_no_envelope_socket(base_ledger, seeded):
    # Ordinary flat_bar (no envelope_socket, monkeypatched or otherwise) as the "housing" — the real,
    # zero-adopter-today case every existing catalog subsystem is actually in.
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, "flat_bar", "housing1")
    led.instances["housing1"].wraps = [root_id, "member2"]

    result = compute_envelope(led, "housing1")
    assert result.ok is False
    assert "flat_bar" in result.reason
    assert "envelope_socket" in result.reason


def test_compute_envelope_rejected_for_empty_wraps(base_ledger, seeded, housing_model):
    led, _root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    # wraps left at its default [] — never set.

    result = compute_envelope(led, "housing1")
    assert result.ok is False
    assert "housing1" in result.reason
    assert "empty" in result.reason


def test_compute_envelope_rejected_for_a_dangling_wraps_member(base_ledger, seeded, housing_model):
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = [root_id, "member2", "ghost_member"]

    result = compute_envelope(led, "housing1")
    assert result.ok is False
    # precise about WHICH member is missing — not just "ok is False"
    assert "ghost_member" in result.reason
    assert "unknown instance id" in result.reason


def test_compute_envelope_rejected_for_multiple_dangling_wraps_members(base_ledger, seeded, housing_model):
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["ghost_a", "ghost_b"]

    result = compute_envelope(led, "housing1")
    assert result.ok is False
    assert "ghost_a" in result.reason
    assert "ghost_b" in result.reason


def test_compute_envelope_rejected_when_no_wraps_member_has_buildable_geometry(base_ledger, seeded, housing_model):
    # standoff_frame is an assembly-template MASTER node (build=None) — raw_build/placed_solid/
    # world_bbox are all None for it (confirmed directly by test_geometry_query.py's own tests), so a
    # wraps list containing ONLY it must fail group_world_bbox entirely, not silently produce an empty
    # (0,0,0) envelope.
    led, _root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, "standoff_frame", "frame1")
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["frame1"]

    result = compute_envelope(led, "housing1")
    assert result.ok is False
    assert "frame1" in result.reason


# ------- housing_alignment_transform (2026-08-06, R5 fix — position, not just size, must be derived) --


def test_housing_alignment_transform_targets_the_groups_real_world_center(base_ledger, seeded, housing_model):
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = [root_id, "member2"]
    result = compute_envelope(led, "housing1")
    assert result.ok is True

    t = housing_alignment_transform(led, "housing1", result)
    assert t is not None
    assert (t.x_mm, t.y_mm, t.z_mm) == pytest.approx((47.5, 0.0, 0.0))
    assert (t.rx_deg, t.ry_deg, t.rz_deg) == pytest.approx((0.0, 0.0, 0.0))


def test_housing_alignment_transform_preserves_the_housings_own_existing_rotation(base_ledger, seeded, housing_model):
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = [root_id, "member2"]
    led.instances["housing1"].transform = Transform(x_mm=1.0, y_mm=2.0, z_mm=3.0, rz_deg=45.0)
    result = compute_envelope(led, "housing1")

    t = housing_alignment_transform(led, "housing1", result)
    assert t is not None
    assert (t.x_mm, t.y_mm, t.z_mm) == pytest.approx((47.5, 0.0, 0.0))
    assert t.rz_deg == pytest.approx(45.0)  # rotation carried through, only position realigned


def test_housing_alignment_transform_is_none_when_the_envelope_is_unresolved():
    result = EnvelopeComputeResult(ok=False, reason="wraps list is empty")
    # a bare object() stand-in for the ledger is safe here: result.ok is False short-circuits before
    # this function ever touches `ledger.instances`.
    assert housing_alignment_transform(object(), "housing1", result) is None


def test_housing_alignment_transform_is_none_when_center_keys_are_missing():
    # e.g. an older/partial EnvelopeComputeResult (or a test double) that never populated the new
    # coarse_bbox_center_* keys — must never guess a position from an incomplete result.
    result = EnvelopeComputeResult(ok=True, values={"hull_bbox_x_mm": 10.0})
    assert housing_alignment_transform(object(), "housing1", result) is None


def test_housing_alignment_transform_is_none_for_an_unknown_housing_instance(base_ledger, seeded):
    led = seeded(base_ledger, "flat_bar")
    result = EnvelopeComputeResult(ok=True, values={
        "coarse_bbox_center_x_mm": 1.0, "coarse_bbox_center_y_mm": 2.0, "coarse_bbox_center_z_mm": 3.0,
    })
    assert housing_alignment_transform(led, "ghost_housing", result) is None
