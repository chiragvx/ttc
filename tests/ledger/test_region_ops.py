"""RegionOp / apply_region_op behaviour — the keep-out/keep-in-box counterpart to
test_instance_ops.py's InstanceOp coverage. Unlike InstanceOp/ConnectionOp/CouplingOp/FitOp, a Region
is a pure geometric ANNOTATION (packages/ledger/schema.py::Region's own docstring): apply_region_op
needs no injected callables at all — `host_instance` is checked directly against `ledger.instances`,
already in scope in this registry-free package.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.ledger.apply import ApplyStatus, apply_region_op
from packages.ledger.deltas import RegionOp, parameter_delta_tool_schema
from packages.ledger.schema import Region

ADD_KW = dict(
    op="add_region",
    host_instance="root",
    kind="keep_out",
    label="gear_train_clearance",
    x_mm=1.0, y_mm=2.0, z_mm=3.0,
    dx_mm=10.0, dy_mm=20.0, dz_mm=5.0,
)


# --- schema-level regression: region_ops must actually reach the LLM tool schema -----------------


def test_region_ops_present_in_tool_schema():
    schema = parameter_delta_tool_schema()
    assert "region_ops" in schema["properties"]
    ro = schema["properties"]["region_ops"]
    assert ro["type"] == "array"
    ref = ro["items"]["$ref"].rsplit("/", 1)[-1]
    defs = schema["$defs"]
    assert ref in defs
    region_op_schema = defs[ref]
    assert "op" in region_op_schema["properties"]
    op_enum = region_op_schema["properties"]["op"]
    assert set(op_enum.get("enum", [])) == {"add_region", "remove_region"}
    # extra="forbid" must survive into the wire schema (strict tool-use — no smuggled fields)
    assert region_op_schema.get("additionalProperties") is False


# --- Region model itself: backward-compatible default, positive-extent floor ---------------------


def test_regions_defaults_to_empty_list(base_ledger):
    assert base_ledger.regions == []


def test_region_model_rejects_non_positive_extents():
    for bad_field in ("dx_mm", "dy_mm", "dz_mm"):
        kwargs = dict(id="r1", host_instance="root", kind="keep_out", label="l",
                     x_mm=0.0, y_mm=0.0, z_mm=0.0, dx_mm=1.0, dy_mm=1.0, dz_mm=1.0)
        kwargs[bad_field] = 0.0
        with pytest.raises(ValidationError):
            Region(**kwargs)


def test_region_model_extra_field_forbidden():
    with pytest.raises(ValidationError):
        Region(id="r1", host_instance="root", kind="keep_out", label="l",
              x_mm=0.0, y_mm=0.0, z_mm=0.0, dx_mm=1.0, dy_mm=1.0, dz_mm=1.0,
              unexpected_field=1)


# --- add_region ------------------------------------------------------------------------------------


def test_add_region_success_auto_generated_id(base_ledger):
    op = RegionOp(**ADD_KW)
    new, out = apply_region_op(base_ledger, op)

    assert out.status is ApplyStatus.APPLIED
    assert out.region_id == "region_1"
    assert out.region is not None
    assert out.region.host_instance == "root"
    assert out.region.kind == "keep_out"
    assert out.region.label == "gear_train_clearance"
    assert (out.region.x_mm, out.region.y_mm, out.region.z_mm) == (1.0, 2.0, 3.0)
    assert (out.region.dx_mm, out.region.dy_mm, out.region.dz_mm) == (10.0, 20.0, 5.0)
    assert len(new.regions) == 1
    assert new.regions[0].id == "region_1"
    assert base_ledger.regions == []  # original untouched


def test_add_region_with_explicit_id(base_ledger):
    op = RegionOp(**{**ADD_KW, "id": "my_region"})
    new, out = apply_region_op(base_ledger, op)
    assert out.status is ApplyStatus.APPLIED
    assert out.region_id == "my_region"
    assert new.regions[0].id == "my_region"


def test_add_region_auto_generated_id_skips_taken_names(base_ledger):
    led1, out1 = apply_region_op(base_ledger, RegionOp(**ADD_KW))
    assert out1.region_id == "region_1"
    led2, out2 = apply_region_op(led1, RegionOp(**ADD_KW))
    assert out2.status is ApplyStatus.APPLIED
    assert out2.region_id == "region_2"
    assert {r.id for r in led2.regions} == {"region_1", "region_2"}


def test_add_region_rejected_for_duplicate_id(base_ledger):
    led1, out1 = apply_region_op(base_ledger, RegionOp(**{**ADD_KW, "id": "dup"}))
    assert out1.status is ApplyStatus.APPLIED
    led2, out2 = apply_region_op(led1, RegionOp(**{**ADD_KW, "id": "dup"}))
    assert out2.status is ApplyStatus.REJECTED
    assert "already exists" in out2.message
    assert led2 is led1


def test_add_region_rejected_for_unknown_host_instance(base_ledger):
    op = RegionOp(**{**ADD_KW, "host_instance": "ghost"})
    new, out = apply_region_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "ghost" in out.message
    assert new is base_ledger
    assert new.regions == []


@pytest.mark.parametrize("missing_field", [
    "host_instance", "kind", "label", "x_mm", "y_mm", "z_mm", "dx_mm", "dy_mm", "dz_mm",
])
def test_add_region_rejected_for_each_missing_required_field(base_ledger, missing_field):
    kwargs = dict(ADD_KW)
    kwargs[missing_field] = None
    op = RegionOp(**kwargs)
    new, out = apply_region_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert missing_field in out.message
    assert new is base_ledger


@pytest.mark.parametrize("bad_field", ["dx_mm", "dy_mm", "dz_mm"])
def test_add_region_rejected_for_non_positive_extent_not_clamped(base_ledger, bad_field):
    """Box dims must be positive — REJECT, never silently clamp (CLAUDE.md's own "never weaken a
    check" posture, mirroring CutFeature's dia_mm/length_mm/width_mm > 0 floor)."""
    for bad_value in (0.0, -5.0):
        kwargs = dict(ADD_KW)
        kwargs[bad_field] = bad_value
        op = RegionOp(**kwargs)
        new, out = apply_region_op(base_ledger, op)
        assert out.status is ApplyStatus.REJECTED
        assert "> 0" in out.message
        assert new is base_ledger
        assert new.regions == []  # never silently applied with a clamped value


def test_add_region_keep_in_kind(base_ledger):
    op = RegionOp(**{**ADD_KW, "kind": "keep_in"})
    new, out = apply_region_op(base_ledger, op)
    assert out.status is ApplyStatus.APPLIED
    assert out.region.kind == "keep_in"


# --- remove_region ----------------------------------------------------------------------------


def test_remove_region_success(base_ledger):
    led, add_out = apply_region_op(base_ledger, RegionOp(**{**ADD_KW, "id": "r1"}))
    assert add_out.status is ApplyStatus.APPLIED

    new, out = apply_region_op(led, RegionOp(op="remove_region", id="r1"))
    assert out.status is ApplyStatus.APPLIED
    assert out.region is not None and out.region.id == "r1"
    assert new.regions == []
    assert led.regions[0].id == "r1"  # prior ledger untouched


def test_remove_region_rejected_for_missing_id(base_ledger):
    new, out = apply_region_op(base_ledger, RegionOp(op="remove_region"))
    assert out.status is ApplyStatus.REJECTED
    assert new is base_ledger


def test_remove_region_rejected_for_unknown_id(base_ledger):
    new, out = apply_region_op(base_ledger, RegionOp(op="remove_region", id="ghost"))
    assert out.status is ApplyStatus.REJECTED
    assert "ghost" in out.message
    assert new is base_ledger
