"""InstanceOp / apply_instance_op behaviour — the multi-instance-assembly-composition counterpart to
test_feature_ops.py's FeatureOp coverage. `packages/ledger/CLAUDE.md` forbids this package from
knowing about `packages.subsystems`, so `apply_instance_op` takes `known_subsystem_types` /
`seed_defaults` / `reconcile` as INJECTED callables/values (same style as `apply_feature_op`'s
`build_part`) — these tests bind them to the real subsystem registry, exactly like the "next stage"
(transport/agents wiring) will.
"""

from __future__ import annotations

import pytest

from packages.ledger.apply import ApplyStatus, apply_instance_op
from packages.ledger.deltas import InstanceOp, parameter_delta_tool_schema
from packages.ledger.schema import Instance

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem_model
from packages.subsystems.assembly_template import reconcile_children
from packages.subsystems.base import seed_instance

KNOWN = frozenset(SUBSYSTEM_REGISTRY)


def _seed_defaults(subsystem_type: str, instance_id: str, parent_id) -> Instance:
    model = get_subsystem_model(subsystem_type)
    return seed_instance(model, instance_id, parent_id=parent_id)


# --- schema-level regression: instance_ops must actually reach the LLM tool schema ---------------


def test_instance_ops_present_in_tool_schema():
    schema = parameter_delta_tool_schema()
    assert "instance_ops" in schema["properties"]
    io = schema["properties"]["instance_ops"]
    assert io["type"] == "array"
    ref = io["items"]["$ref"].rsplit("/", 1)[-1]
    defs = schema["$defs"]
    assert ref in defs
    instance_op_schema = defs[ref]
    assert "op" in instance_op_schema["properties"]
    op_enum = instance_op_schema["properties"]["op"]
    assert set(op_enum.get("enum", [])) == {"add_instance", "remove_instance", "move_instance"}
    # extra="forbid" must survive into the wire schema (strict tool-use — no smuggled fields)
    assert instance_op_schema.get("additionalProperties") is False


# --- add_instance ---------------------------------------------------------------------------------


def test_add_instance_success_auto_generated_id(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="standoff")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)

    assert out.status is ApplyStatus.APPLIED
    assert out.instance_id == "standoff_1"
    assert out.instance is not None
    assert out.instance.subsystem_type == "standoff"
    assert "standoff_1" in new.instances
    assert new.instances["standoff_1"].parent_id is None  # omitted parent_id -> top-level
    # default params were seeded from the subsystem's own ParamSpec defaults, not empty
    expected_defaults = get_subsystem_model("standoff").defaults()
    assert set(new.instances["standoff_1"].params) == set(expected_defaults)
    assert "standoff_1" not in base_ledger.instances  # original untouched


def test_add_instance_with_explicit_id(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="standoff", instance_id="my_standoff")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)

    assert out.status is ApplyStatus.APPLIED
    assert out.instance_id == "my_standoff"
    assert "my_standoff" in new.instances


def test_add_instance_auto_generated_id_skips_taken_names(base_ledger):
    op1 = InstanceOp(op="add_instance", subsystem_type="standoff")
    led1, out1 = apply_instance_op(base_ledger, op1, KNOWN, seed_defaults=_seed_defaults)
    assert out1.instance_id == "standoff_1"

    op2 = InstanceOp(op="add_instance", subsystem_type="standoff")
    led2, out2 = apply_instance_op(led1, op2, KNOWN, seed_defaults=_seed_defaults)
    assert out2.status is ApplyStatus.APPLIED
    assert out2.instance_id == "standoff_2"
    assert {"standoff_1", "standoff_2"} <= set(led2.instances)


def test_add_instance_rejected_for_duplicate_id(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="standoff", instance_id="root")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert "already exists" in out.message
    assert new is base_ledger


def test_add_instance_rejected_for_unknown_subsystem_type(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="satellite_bus")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert "satellite_bus" in out.message
    assert "unknown subsystem_type" in out.message
    assert new is base_ledger


def test_add_instance_rejected_for_missing_subsystem_type(base_ledger):
    op = InstanceOp(op="add_instance")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert new is base_ledger


def test_add_instance_falls_back_to_top_level_for_nonexistent_parent_id(base_ledger):
    """A guessed/stale parent_id (e.g. an LLM assuming a part named "root" exists) never blocks the
    add — it's not a physical invariant, just a reference that didn't resolve. Falls back to a
    top-level part, with the fallback noted in the outcome message, rather than rejecting the op
    outright (see packages/ledger/apply.py::resolve_instance_parent)."""
    op = InstanceOp(op="add_instance", subsystem_type="standoff", parent_id="nope")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    assert out.instance is not None and out.instance.parent_id is None
    assert "nope" in out.message and "top-level" in out.message
    assert out.instance_id in new.instances


def test_add_instance_requires_seed_defaults(base_ledger):
    """Without an injected seed_defaults, there is no pure-ledger way to materialize the new
    instance's default params — REJECTED, never silently skipped."""
    op = InstanceOp(op="add_instance", subsystem_type="standoff")
    _, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=None)
    assert out.status is ApplyStatus.REJECTED
    assert "seed_defaults" in out.message


def test_add_instance_full_explicit_transform_positions_exactly(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="standoff", x_mm=10.0, y_mm=20.0, z_mm=30.0)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    inst = new.instances[out.instance_id]
    assert inst.transform is not None
    assert inst.transform.x_mm == pytest.approx(10.0)
    assert inst.transform.y_mm == pytest.approx(20.0)
    assert inst.transform.z_mm == pytest.approx(30.0)


def test_add_instance_partial_transform_rejected(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="standoff", x_mm=10.0)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert new is base_ledger
    assert not any(iid.startswith("standoff") for iid in new.instances)


def test_add_instance_no_transform_leaves_transform_none(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="standoff")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    assert new.instances[out.instance_id].transform is None  # auto-layout applies later


def test_add_instance_position_and_rotation_together_applied(base_ledger):
    """Position + rotation both given -> APPLIED, with the resulting Transform carrying the exact
    rotation values (e.g. orienting a longeron's local length axis along a different global axis)."""
    op = InstanceOp(op="add_instance", subsystem_type="standoff",
                    x_mm=10.0, y_mm=20.0, z_mm=30.0,
                    rx_deg=0.0, ry_deg=90.0, rz_deg=45.0)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    inst = new.instances[out.instance_id]
    assert inst.transform is not None
    assert inst.transform.x_mm == pytest.approx(10.0)
    assert inst.transform.y_mm == pytest.approx(20.0)
    assert inst.transform.z_mm == pytest.approx(30.0)
    assert inst.transform.rx_deg == pytest.approx(0.0)
    assert inst.transform.ry_deg == pytest.approx(90.0)
    assert inst.transform.rz_deg == pytest.approx(45.0)


def test_add_instance_rotation_without_position_rejected(base_ledger):
    """Rotation given but position omitted -> REJECTED: auto-layout has no way to place a rotated
    part from an unrotated bounding box, so this dependency is enforced rather than silently
    defaulting position to origin."""
    op = InstanceOp(op="add_instance", subsystem_type="standoff",
                    rx_deg=0.0, ry_deg=90.0, rz_deg=0.0)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert "rotation" in out.message.lower()
    assert "position" in out.message.lower()
    assert new is base_ledger


def test_add_instance_partial_rotation_rejected(base_ledger):
    """Partial rotation (only rx_deg set) -> REJECTED, mirroring the existing partial-position
    test: a partial spec would silently default the missing axes to 0."""
    op = InstanceOp(op="add_instance", subsystem_type="standoff",
                    x_mm=10.0, y_mm=20.0, z_mm=30.0, rx_deg=15.0)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert new is base_ledger
    assert not any(iid.startswith("standoff") for iid in new.instances)


def test_add_instance_position_only_rotation_defaults_to_zero(base_ledger):
    """Position-only (no rotation, exactly as before) -> still APPLIED, with rotation defaulting to
    0.0 on the Transform — confirms no regression for existing position-only callers."""
    op = InstanceOp(op="add_instance", subsystem_type="standoff", x_mm=10.0, y_mm=20.0, z_mm=30.0)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    inst = new.instances[out.instance_id]
    assert inst.transform is not None
    assert inst.transform.rx_deg == 0.0
    assert inst.transform.ry_deg == 0.0
    assert inst.transform.rz_deg == 0.0


def test_add_instance_assembly_template_reconciles_children(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="table", instance_id="table_1")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults,
                                 reconcile=reconcile_children)
    assert out.status is ApplyStatus.APPLIED
    assert "table_1" in new.instances
    # table's default leg_count is 4 -> top + leg0..leg3, all real sibling instances
    children = {iid for iid, inst in new.instances.items() if inst.parent_id == "table_1"}
    assert children == {"table_1_top", "table_1_leg0", "table_1_leg1", "table_1_leg2", "table_1_leg3"}


def test_add_instance_without_reconcile_skips_children(base_ledger):
    """reconcile is optional — omitting it must not crash, it just leaves an assembly-template
    instance childless until a caller that cares reconciles later."""
    op = InstanceOp(op="add_instance", subsystem_type="table", instance_id="table_1")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults, reconcile=None)
    assert out.status is ApplyStatus.APPLIED
    assert "table_1" in new.instances
    assert not any(inst.parent_id == "table_1" for inst in new.instances.values())


# --- remove_instance --------------------------------------------------------------------------


def test_remove_instance_success(base_ledger):
    add_op = InstanceOp(op="add_instance", subsystem_type="standoff", instance_id="standoff_1")
    led, add_out = apply_instance_op(base_ledger, add_op, KNOWN, seed_defaults=_seed_defaults)
    assert add_out.status is ApplyStatus.APPLIED

    rm_op = InstanceOp(op="remove_instance", instance_id="standoff_1")
    new, out = apply_instance_op(led, rm_op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    assert out.instance is not None and out.instance.id == "standoff_1"
    assert "standoff_1" not in new.instances
    assert "standoff_1" in led.instances  # prior ledger untouched


def test_remove_instance_allowed_for_childless_root(base_ledger):
    """2026-07-04: root removal is only blocked by having children (checked above by
    test_remove_instance_rejected_for_instance_with_children) — a childless root, the state every
    "undo my very first add_instance" hits, must be removable, returning to an empty project."""
    op = InstanceOp(op="remove_instance", instance_id=base_ledger.root_id)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    assert new.instances == {}


def test_remove_instance_rejected_for_unknown_id(base_ledger):
    op = InstanceOp(op="remove_instance", instance_id="ghost")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert "ghost" in out.message
    assert new is base_ledger


def test_remove_instance_rejected_for_missing_instance_id(base_ledger):
    op = InstanceOp(op="remove_instance")
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert new is base_ledger


def test_remove_instance_rejected_for_instance_with_children(base_ledger):
    op = InstanceOp(op="add_instance", subsystem_type="table", instance_id="table_1")
    led, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults,
                                 reconcile=reconcile_children)
    assert out.status is ApplyStatus.APPLIED

    rm_op = InstanceOp(op="remove_instance", instance_id="table_1")
    new, rm_out = apply_instance_op(led, rm_op, KNOWN, seed_defaults=_seed_defaults)
    assert rm_out.status is ApplyStatus.REJECTED
    assert "children" in rm_out.message
    assert new is led


# --- move_instance -----------------------------------------------------------------------------
#
# THE CONFIRMED BUG this covers: a live test showed the copilot correctly wanting to reposition an
# ALREADY-PLACED instance ("move the pod on top of the wing") with no legal way to say that in the
# schema. move_instance is the fix.


def _add(ledger, subsystem_type="standoff", instance_id="standoff_1", **kw):
    op = InstanceOp(op="add_instance", subsystem_type=subsystem_type, instance_id=instance_id, **kw)
    return apply_instance_op(ledger, op, KNOWN, seed_defaults=_seed_defaults)


def test_move_instance_happy_path_moves_and_captures_previous(base_ledger):
    led, add_out = _add(base_ledger, x_mm=1.0, y_mm=2.0, z_mm=3.0)
    assert add_out.status is ApplyStatus.APPLIED

    move_op = InstanceOp(op="move_instance", instance_id="standoff_1", x_mm=10.0, y_mm=20.0, z_mm=30.0)
    new, out = apply_instance_op(led, move_op, KNOWN, seed_defaults=_seed_defaults)

    assert out.status is ApplyStatus.APPLIED
    assert out.instance_id == "standoff_1"
    # `instance` carries the POST-move state
    assert out.instance is not None
    assert out.instance.transform.x_mm == pytest.approx(10.0)
    assert out.instance.transform.y_mm == pytest.approx(20.0)
    assert out.instance.transform.z_mm == pytest.approx(30.0)
    # `previous_instance` carries the PRE-move state
    assert out.previous_instance is not None
    assert out.previous_instance.transform.x_mm == pytest.approx(1.0)
    assert out.previous_instance.transform.y_mm == pytest.approx(2.0)
    assert out.previous_instance.transform.z_mm == pytest.approx(3.0)
    # the new ledger reflects the move; the prior ledger is untouched
    assert new.instances["standoff_1"].transform.x_mm == pytest.approx(10.0)
    assert led.instances["standoff_1"].transform.x_mm == pytest.approx(1.0)


def test_move_instance_missing_instance_id_rejected(base_ledger):
    op = InstanceOp(op="move_instance", x_mm=1.0, y_mm=2.0, z_mm=3.0)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert "instance_id" in out.message
    assert new is base_ledger


def test_move_instance_unknown_instance_id_rejected(base_ledger):
    op = InstanceOp(op="move_instance", instance_id="ghost", x_mm=1.0, y_mm=2.0, z_mm=3.0)
    new, out = apply_instance_op(base_ledger, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert "ghost" in out.message
    assert new is base_ledger


def test_move_instance_partial_position_rejected(base_ledger):
    led, add_out = _add(base_ledger)
    assert add_out.status is ApplyStatus.APPLIED

    op = InstanceOp(op="move_instance", instance_id="standoff_1", x_mm=10.0, y_mm=20.0)
    new, out = apply_instance_op(led, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert "x_mm/y_mm/z_mm" in out.message
    assert new is led
    assert led.instances["standoff_1"].transform is None  # unchanged


def test_move_instance_no_position_at_all_rejected(base_ledger):
    """Unlike add_instance (where omitting all three means auto-layout), move_instance has no
    auto-layout fallback — an explicit move with no position at all is REJECTED, not a no-op."""
    led, add_out = _add(base_ledger)
    assert add_out.status is ApplyStatus.APPLIED

    op = InstanceOp(op="move_instance", instance_id="standoff_1")
    new, out = apply_instance_op(led, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert new is led


def test_move_instance_partial_rotation_rejected(base_ledger):
    led, add_out = _add(base_ledger, x_mm=1.0, y_mm=2.0, z_mm=3.0)
    assert add_out.status is ApplyStatus.APPLIED

    op = InstanceOp(op="move_instance", instance_id="standoff_1",
                    x_mm=10.0, y_mm=20.0, z_mm=30.0, rx_deg=15.0)
    new, out = apply_instance_op(led, op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.REJECTED
    assert new is led


def test_move_instance_no_rotation_given_keeps_current_rotation(base_ledger):
    """The single most important behavioral test: a move with NO rotation given must NOT reset the
    instance's rotation to 0 — it keeps whatever rotation it already had."""
    led, add_out = _add(base_ledger, x_mm=1.0, y_mm=2.0, z_mm=3.0, rx_deg=10.0, ry_deg=20.0, rz_deg=30.0)
    assert add_out.status is ApplyStatus.APPLIED
    assert led.instances["standoff_1"].transform.rx_deg == pytest.approx(10.0)

    move_op = InstanceOp(op="move_instance", instance_id="standoff_1", x_mm=100.0, y_mm=200.0, z_mm=300.0)
    new, out = apply_instance_op(led, move_op, KNOWN, seed_defaults=_seed_defaults)

    assert out.status is ApplyStatus.APPLIED
    moved = new.instances["standoff_1"]
    assert moved.transform.x_mm == pytest.approx(100.0)
    assert moved.transform.y_mm == pytest.approx(200.0)
    assert moved.transform.z_mm == pytest.approx(300.0)
    # rotation UNCHANGED, not reset to 0
    assert moved.transform.rx_deg == pytest.approx(10.0)
    assert moved.transform.ry_deg == pytest.approx(20.0)
    assert moved.transform.rz_deg == pytest.approx(30.0)


def test_move_instance_no_prior_transform_defaults_rotation_to_zero(base_ledger):
    """An instance with NO transform at all (auto-layout, never explicitly placed) has no "current"
    rotation to preserve — moving it with no rotation given falls back to identity (0/0/0), not a
    crash on `target.transform` being None."""
    led, add_out = _add(base_ledger)  # no x/y/z -> transform stays None (auto-layout)
    assert add_out.status is ApplyStatus.APPLIED
    assert led.instances["standoff_1"].transform is None

    move_op = InstanceOp(op="move_instance", instance_id="standoff_1", x_mm=5.0, y_mm=6.0, z_mm=7.0)
    new, out = apply_instance_op(led, move_op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    moved = new.instances["standoff_1"]
    assert moved.transform.rx_deg == 0.0
    assert moved.transform.ry_deg == 0.0
    assert moved.transform.rz_deg == 0.0


def test_move_instance_with_rotation_given_uses_new_rotation(base_ledger):
    led, add_out = _add(base_ledger, x_mm=1.0, y_mm=2.0, z_mm=3.0, rx_deg=10.0, ry_deg=20.0, rz_deg=30.0)
    assert add_out.status is ApplyStatus.APPLIED

    move_op = InstanceOp(op="move_instance", instance_id="standoff_1",
                        x_mm=100.0, y_mm=200.0, z_mm=300.0,
                        rx_deg=45.0, ry_deg=90.0, rz_deg=0.0)
    new, out = apply_instance_op(led, move_op, KNOWN, seed_defaults=_seed_defaults)
    assert out.status is ApplyStatus.APPLIED
    moved = new.instances["standoff_1"]
    assert moved.transform.rx_deg == pytest.approx(45.0)
    assert moved.transform.ry_deg == pytest.approx(90.0)
    assert moved.transform.rz_deg == pytest.approx(0.0)
