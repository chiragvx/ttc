"""FeatureOp / apply_feature_op behaviour — the hole/pocket/slot counterpart to test_apply.py's
ParameterDelta / apply_delta coverage. `packages/ledger/CLAUDE.md` forbids OCCT/build123d imports in
this package, so `apply_feature_op` takes `build_part` as an INJECTED callable (same style as
`apply_delta`'s `domain_checks`/`cascade_rules`) — these tests supply a real one, bound to
`get_subsystem(...).geometry_builder`, exactly like the "next stage" (transport/agents wiring) will.
"""

from __future__ import annotations

import importlib.util

import pytest

from packages.ledger.apply import ApplyStatus, apply_feature_op
from packages.ledger.deltas import FeatureOp, parameter_delta_tool_schema
from packages.ledger.schema import CutFeature

HAS_B123D = importlib.util.find_spec("build123d") is not None

pytestmark_b123d = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")


# --- schema-level regression: feature_ops must actually reach the LLM tool schema ----------------


def test_feature_ops_present_in_tool_schema():
    schema = parameter_delta_tool_schema()
    assert "feature_ops" in schema["properties"]
    fo = schema["properties"]["feature_ops"]
    assert fo["type"] == "array"
    ref = fo["items"]["$ref"].rsplit("/", 1)[-1]
    defs = schema["$defs"]
    assert ref in defs
    feature_op_schema = defs[ref]
    for required_prop in ("op", "instance_id"):
        assert required_prop in feature_op_schema["properties"]
    op_enum = feature_op_schema["properties"]["op"]
    assert set(op_enum.get("enum", [])) == {"add_feature", "update_feature", "remove_feature"}
    # extra="forbid" must survive into the wire schema (strict tool-use — no smuggled fields)
    assert feature_op_schema.get("additionalProperties") is False


# --- geometry-free paths: instance/feature lookups fail before any build is attempted ------------


def test_add_feature_rejected_for_unknown_instance(base_ledger):
    op = FeatureOp(op="add_feature", instance_id="nope", kind="hole", shape="circle",
                   dia_mm=6.0, depth_mm=3.0)
    new, out = apply_feature_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "nope" in out.message
    assert new is base_ledger


def test_add_feature_rejected_missing_shape_field(base_ledger):
    # circle without dia_mm
    op = FeatureOp(op="add_feature", instance_id="root", kind="hole", shape="circle", depth_mm=3.0)
    _, out = apply_feature_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "dia_mm" in out.message

    # rect without length_mm/width_mm
    op2 = FeatureOp(op="add_feature", instance_id="root", kind="pocket", shape="rect", depth_mm=3.0)
    _, out2 = apply_feature_op(base_ledger, op2)
    assert out2.status is ApplyStatus.REJECTED
    assert "length_mm" in out2.message


def test_update_feature_rejected_for_unknown_feature_id(base_ledger):
    op = FeatureOp(op="update_feature", instance_id="root", feature_id="ghost", dia_mm=5.0)
    new, out = apply_feature_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "ghost" in out.message
    assert new is base_ledger


def test_remove_feature_rejected_for_unknown_feature_id(base_ledger):
    op = FeatureOp(op="remove_feature", instance_id="root", feature_id="ghost")
    new, out = apply_feature_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert new is base_ledger


def test_remove_feature_removes_existing(base_ledger):
    feature = CutFeature(id="h0", kind="hole", shape="circle", dia_mm=4.0, depth_mm=3.0)
    root = base_ledger.instances["root"].model_copy(update={"cut_features": [feature]})
    led = base_ledger.model_copy(update={"instances": {**base_ledger.instances, "root": root}})

    op = FeatureOp(op="remove_feature", instance_id="root", feature_id="h0")
    new, out = apply_feature_op(led, op)
    assert out.status is ApplyStatus.APPLIED
    assert out.feature is not None and out.feature.id == "h0"
    assert new.instances["root"].cut_features == []
    assert led.instances["root"].cut_features == [feature]  # original untouched


def test_add_feature_requires_build_part(base_ledger):
    """Without an injected build_part, add/update can't resolve depth or validate fit — REJECTED,
    never silently skipped."""
    op = FeatureOp(op="add_feature", instance_id="root", kind="hole", shape="circle",
                   dia_mm=6.0, depth_mm=3.0)
    _, out = apply_feature_op(base_ledger, op, build_part=None)
    assert out.status is ApplyStatus.REJECTED
    assert "geometry builder" in out.message


# --- geometry-backed paths: need a real subsystem + build123d ------------------------------------


def _flat_bar_ledger(base_ledger):
    from packages.subsystems import get_subsystem

    return get_subsystem("flat_bar").seed_defaults(base_ledger)


def _build_part(ledger, instance_id):
    from packages.subsystems import get_subsystem

    inst = ledger.instances[instance_id]
    return get_subsystem(inst.subsystem_type).geometry_builder(ledger, instance_id)


@pytestmark_b123d
def test_add_feature_success_stores_concrete_depth_and_changes_geometry(base_ledger):
    led = _flat_bar_ledger(base_ledger)  # flat_bar defaults: length=100, width=20, thickness=5 mm
    op = FeatureOp(op="add_feature", instance_id="root", kind="hole", shape="circle",
                   dia_mm=6.0, depth_mm=4.0)
    new, out = apply_feature_op(led, op, build_part=_build_part)

    assert out.status is ApplyStatus.APPLIED
    assert out.feature is not None
    assert out.feature.depth_mm == pytest.approx(4.0)
    assert out.feature.id  # a fresh id was minted

    stored = new.instances["root"].cut_features
    assert len(stored) == 1
    assert stored[0].id == out.feature.id
    assert stored[0].depth_mm == pytest.approx(4.0)

    base_part = _build_part(led, "root")
    new_part = _build_part(new, "root")
    assert new_part.solid.volume < base_part.solid.volume
    assert f"cut[{out.feature.id}].feature" in new_part.tags

    assert led.instances["root"].cut_features == []  # original ledger untouched


@pytestmark_b123d
def test_add_feature_through_resolves_concrete_positive_depth(base_ledger):
    led = _flat_bar_ledger(base_ledger)  # thickness = 5.0 mm
    op = FeatureOp(op="add_feature", instance_id="root", kind="hole", shape="circle",
                   dia_mm=5.0, through=True)
    new, out = apply_feature_op(led, op, build_part=_build_part)

    assert out.status is ApplyStatus.APPLIED
    assert out.feature is not None
    assert out.feature.depth_mm > 0
    # the TRUE host Z-extent, not an inflated margin -- `depth_mm` feeds `swept_volume_mm3`'s analytic
    # mass/volume accounting directly (packages/subsystems/cut_features.py), so it must stay the honest
    # material-penetration depth; the OCCT cutter's own robustness overhang lives entirely inside
    # `apply_cut_features` and never leaks into this stored, ledger-visible fact.
    assert out.feature.depth_mm == pytest.approx(5.0)  # host Z-extent

    part = _build_part(new, "root")
    assert len(part.solid.solids()) == 1


@pytestmark_b123d
def test_add_feature_rejected_when_oversized_relative_to_host(base_ledger):
    led = _flat_bar_ledger(base_ledger)  # width = 20 mm -> margin-adjusted max footprint = 17 mm
    op = FeatureOp(op="add_feature", instance_id="root", kind="hole", shape="circle",
                   dia_mm=25.0, depth_mm=4.0)
    new, out = apply_feature_op(led, op, build_part=_build_part)

    assert out.status is ApplyStatus.CONFLICT
    assert "footprint" in out.message
    assert new.instances["root"].cut_features == []  # nothing committed


@pytestmark_b123d
def test_add_feature_rejected_when_depth_exceeds_host_thickness(base_ledger):
    """A partial-depth (non-`through`) cut deeper than the host's real Z-extent is physically
    impossible to actually remove that much material for -- a real OCCT boolean subtract is bounded
    by what's actually solid there. Storing the inflated `depth_mm` anyway would silently overcount
    `swept_volume_mm3`'s analytic mass/volume accounting past what any real cut could remove (see
    `packages/ledger/apply.py::_depth_violation`). Must be CONFLICT, never silently accepted or
    silently capped."""
    led = _flat_bar_ledger(base_ledger)  # thickness = 5.0 mm
    op = FeatureOp(op="add_feature", instance_id="root", kind="pocket", shape="rect",
                  length_mm=10.0, width_mm=10.0, depth_mm=8.0)
    new, out = apply_feature_op(led, op, build_part=_build_part)

    assert out.status is ApplyStatus.CONFLICT
    assert "thickness" in out.message
    assert new.instances["root"].cut_features == []  # nothing committed


@pytestmark_b123d
def test_add_feature_rejected_when_it_would_sever_the_part(base_ledger):
    """Neither cut is individually oversized (both comfortably pass the footprint-fit check), but
    together they remove the ONLY remaining bridge between two halves of the bar -> the registered
    geometry_builder's single-solid check raises, and apply_feature_op converts that into CONFLICT
    instead of ever committing it."""
    led = _flat_bar_ledger(base_ledger)  # length=100 (X: -50..50), width=20 (Y: -10..10), thickness=5

    # Pre-existing cut (attached directly, bypassing apply_feature_op's own validation — this is
    # simulating already-committed prior state): removes X in [-15,-5], Y in [-10, 9], leaving only a
    # 1 mm bridge at the top edge (Y in [9, 10]) connecting the left and right halves of the bar.
    # depth_mm == the bar's own thickness (5.0), never inflated past the host's real Z-extent (an
    # inflated depth here would trip `apply.py::_depth_violation` on any FUTURE op targeting this
    # instance, and would silently overcount `swept_volume_mm3`'s analytic accounting either way).
    existing = CutFeature(id="root_cut0", kind="pocket", shape="rect",
                          length_mm=10.0, width_mm=19.0, depth_mm=5.0, x_mm=-10.0, y_mm=-0.5)
    root = led.instances["root"].model_copy(update={"cut_features": [existing]})
    led = led.model_copy(update={"instances": {**led.instances, "root": root}})

    # Sanity: the pre-existing cut alone does NOT sever (the 1mm top bridge holds it together).
    assert len(_build_part(led, "root").solid.solids()) == 1

    # Candidate: small footprint (well within the fit margin on both axes), but it exactly removes
    # that last 1mm bridge -> combined with `existing`, the bar is cut clean through at X in [-15,-5].
    # `through=True` (not an explicit depth_mm) resolves to the bar's own real Z-extent, same as
    # `existing` above -- keeping this test's CONFLICT firmly about the severing check below, not
    # about `apply.py::_depth_violation` rejecting an over-deep candidate first.
    op = FeatureOp(op="add_feature", instance_id="root", kind="slot", shape="rect",
                   length_mm=12.0, width_mm=2.0, through=True, x_mm=-10.0, y_mm=9.5)
    new, out = apply_feature_op(led, op, build_part=_build_part)

    assert out.status is ApplyStatus.CONFLICT
    assert new.instances["root"].cut_features == [existing]  # nothing committed beyond pre-existing


@pytestmark_b123d
def test_update_feature_changes_size_and_position(base_ledger):
    led = _flat_bar_ledger(base_ledger)
    add_op = FeatureOp(op="add_feature", instance_id="root", kind="hole", shape="circle",
                       dia_mm=4.0, depth_mm=3.0, x_mm=10.0, y_mm=0.0)
    led, add_out = apply_feature_op(led, add_op, build_part=_build_part)
    assert add_out.status is ApplyStatus.APPLIED
    fid = add_out.feature.id

    update_op = FeatureOp(op="update_feature", instance_id="root", feature_id=fid,
                          dia_mm=6.0, x_mm=-10.0, y_mm=2.0)
    new, out = apply_feature_op(led, update_op, build_part=_build_part)

    assert out.status is ApplyStatus.APPLIED
    assert out.feature.id == fid
    assert out.feature.dia_mm == pytest.approx(6.0)
    assert out.feature.x_mm == pytest.approx(-10.0)
    assert out.feature.y_mm == pytest.approx(2.0)
    assert out.feature.depth_mm == pytest.approx(3.0)  # unspecified on the update -> carried over

    stored = new.instances["root"].cut_features
    assert len(stored) == 1
    assert stored[0].dia_mm == pytest.approx(6.0)
