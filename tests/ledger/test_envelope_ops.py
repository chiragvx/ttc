"""EnvelopeOp / apply_envelope_op behaviour (gearbox-housing-generation initiative Phase 2) — the
`Instance.wraps`-wiring counterpart to test_region_ops.py's RegionOp coverage. Like RegionOp,
apply_envelope_op needs no injected callables at all: `housing_instance`/`member_instance_ids` are
checked directly against `ledger.instances`, already in scope in this registry-free package.

NOTE, unlike test_region_ops.py's own first section: `EnvelopeOp` is NOT yet wired into
`DeltaProposal` (deliberately out of scope for this phase, see `packages/ledger/deltas.py::
EnvelopeOp`'s own docstring — the LLM-facing tool-schema wiring is a later phase's job), so there is
no "present in tool schema" regression test here the way test_region_ops.py has for RegionOp.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.ledger.apply import ApplyStatus, apply_envelope_op
from packages.ledger.deltas import EnvelopeOp
from packages.ledger.schema import Instance


def _with_bare_instances(base_ledger, *instance_ids: str):
    """Add bare, geometry-less Instance stubs alongside `base_ledger`'s own "root" — apply_envelope_op
    only ever checks `ledger.instances` membership, never a subsystem's registry entry or real
    geometry, so a minimal stub (arbitrary subsystem_type, empty params) is all a wrap_group/
    unwrap_group test needs (mirrors test_region_ops.py's own base_ledger-only reliance)."""
    new_instances = dict(base_ledger.instances)
    for iid in instance_ids:
        new_instances[iid] = Instance(id=iid, subsystem_type="stub", params={}, parent_id=None)
    return base_ledger.model_copy(update={"instances": new_instances})


# --- EnvelopeOp model itself: extra="forbid", housing_instance is REQUIRED for every op value -------


def test_envelope_op_model_extra_field_forbidden():
    with pytest.raises(ValidationError):
        EnvelopeOp(op="wrap_group", housing_instance="h1", member_instance_ids=["m1"], unexpected_field=1)


def test_envelope_op_requires_housing_instance_for_every_op_value():
    for op_value in ("wrap_group", "unwrap_group", "resync_envelope"):
        with pytest.raises(ValidationError):
            EnvelopeOp(op=op_value)


def test_instance_wraps_defaults_to_empty_list(base_ledger):
    assert base_ledger.instances["root"].wraps == []


# --- wrap_group ---------------------------------------------------------------------------------


def test_wrap_group_success_sets_wraps(base_ledger):
    led = _with_bare_instances(base_ledger, "m1", "m2")
    op = EnvelopeOp(op="wrap_group", housing_instance="root", member_instance_ids=["m1", "m2"])
    new, out = apply_envelope_op(led, op)

    assert out.status is ApplyStatus.APPLIED
    assert out.housing_instance_id == "root"
    assert out.instance is not None
    assert out.instance.wraps == ["m1", "m2"]
    assert new.instances["root"].wraps == ["m1", "m2"]
    assert led.instances["root"].wraps == []  # original untouched


def test_wrap_group_replaces_the_entire_wraps_list_wholesale(base_ledger):
    led = _with_bare_instances(base_ledger, "m1", "m2", "m3")
    led, out1 = apply_envelope_op(led, EnvelopeOp(op="wrap_group", housing_instance="root",
                                                  member_instance_ids=["m1", "m2"]))
    assert out1.status is ApplyStatus.APPLIED
    assert led.instances["root"].wraps == ["m1", "m2"]

    led, out2 = apply_envelope_op(led, EnvelopeOp(op="wrap_group", housing_instance="root",
                                                  member_instance_ids=["m3"]))
    assert out2.status is ApplyStatus.APPLIED
    # replaced wholesale, not merged/appended
    assert led.instances["root"].wraps == ["m3"]


def test_wrap_group_rejected_for_unknown_housing_instance(base_ledger):
    led = _with_bare_instances(base_ledger, "m1")
    op = EnvelopeOp(op="wrap_group", housing_instance="ghost_housing", member_instance_ids=["m1"])
    new, out = apply_envelope_op(led, op)
    assert out.status is ApplyStatus.REJECTED
    assert "ghost_housing" in out.message
    assert new is led


def test_wrap_group_rejected_for_missing_member_instance_ids(base_ledger):
    op = EnvelopeOp(op="wrap_group", housing_instance="root")
    new, out = apply_envelope_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "member_instance_ids" in out.message
    assert new is base_ledger


def test_wrap_group_rejected_for_empty_member_instance_ids(base_ledger):
    op = EnvelopeOp(op="wrap_group", housing_instance="root", member_instance_ids=[])
    new, out = apply_envelope_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "member_instance_ids" in out.message
    assert new is base_ledger


def test_wrap_group_rejected_for_unknown_member_instance_id(base_ledger):
    led = _with_bare_instances(base_ledger, "m1")
    op = EnvelopeOp(op="wrap_group", housing_instance="root", member_instance_ids=["m1", "ghost_member"])
    new, out = apply_envelope_op(led, op)
    assert out.status is ApplyStatus.REJECTED
    assert "ghost_member" in out.message
    assert new is led
    assert led.instances["root"].wraps == []  # never partially applied


def test_wrap_group_rejected_for_multiple_unknown_member_instance_ids(base_ledger):
    op = EnvelopeOp(op="wrap_group", housing_instance="root", member_instance_ids=["ghost_a", "ghost_b"])
    new, out = apply_envelope_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "ghost_a" in out.message
    assert "ghost_b" in out.message


def test_wrap_group_rejected_when_housing_would_wrap_itself(base_ledger):
    led = _with_bare_instances(base_ledger, "m1")
    op = EnvelopeOp(op="wrap_group", housing_instance="root", member_instance_ids=["root", "m1"])
    new, out = apply_envelope_op(led, op)
    assert out.status is ApplyStatus.REJECTED
    assert "root" in out.message
    assert new is led


# --- unwrap_group --------------------------------------------------------------------------------


def test_unwrap_group_success_clears_wraps(base_ledger):
    led = _with_bare_instances(base_ledger, "m1", "m2")
    led, wrap_out = apply_envelope_op(led, EnvelopeOp(op="wrap_group", housing_instance="root",
                                                       member_instance_ids=["m1", "m2"]))
    assert wrap_out.status is ApplyStatus.APPLIED

    new, out = apply_envelope_op(led, EnvelopeOp(op="unwrap_group", housing_instance="root"))
    assert out.status is ApplyStatus.APPLIED
    assert out.instance is not None
    assert out.instance.wraps == []
    assert new.instances["root"].wraps == []
    assert led.instances["root"].wraps == ["m1", "m2"]  # prior ledger untouched


def test_unwrap_group_rejected_for_unknown_housing_instance(base_ledger):
    op = EnvelopeOp(op="unwrap_group", housing_instance="ghost_housing")
    new, out = apply_envelope_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "ghost_housing" in out.message
    assert new is base_ledger


def test_unwrap_group_rejected_when_wraps_already_empty(base_ledger):
    op = EnvelopeOp(op="unwrap_group", housing_instance="root")
    new, out = apply_envelope_op(base_ledger, op)
    assert out.status is ApplyStatus.REJECTED
    assert "root" in out.message
    assert "empty" in out.message
    assert new is base_ledger


# --- resync_envelope: honest stub, always REJECTED this phase -----------------------------------


def test_resync_envelope_is_a_rejected_stub_even_with_a_live_wraps_list(base_ledger):
    led = _with_bare_instances(base_ledger, "m1")
    led, wrap_out = apply_envelope_op(led, EnvelopeOp(op="wrap_group", housing_instance="root",
                                                       member_instance_ids=["m1"]))
    assert wrap_out.status is ApplyStatus.APPLIED

    new, out = apply_envelope_op(led, EnvelopeOp(op="resync_envelope", housing_instance="root"))
    assert out.status is ApplyStatus.REJECTED
    assert "not yet wired" in out.message
    assert new is led
    assert led.instances["root"].wraps == ["m1"]  # unchanged, no fake recompute happened


def test_resync_envelope_rejected_even_for_an_unknown_housing_instance(base_ledger):
    # Still a clean REJECTED (not a crash) even when housing_instance doesn't exist at all — the stub
    # short-circuits before ever checking ledger.instances (see apply_envelope_op's own branch order).
    new, out = apply_envelope_op(base_ledger, EnvelopeOp(op="resync_envelope", housing_instance="ghost"))
    assert out.status is ApplyStatus.REJECTED
    assert new is base_ledger


# --- unknown op -----------------------------------------------------------------------------------


def test_apply_envelope_op_rejects_a_pydantic_valid_but_unhandled_op_value(base_ledger, monkeypatch):
    # EnvelopeOp.op is a Literal, so an actually-invalid op string can't even construct one — this
    # exercises apply_envelope_op's own defensive `unknown op` fallback the same way apply_region_op's
    # analogous branch is dead-unless-Literal-is-bypassed, via a lightweight stand-in object rather
    # than fighting pydantic's Literal validation.
    class _FakeOp:
        op = "not_a_real_op"
        housing_instance = "root"
        member_instance_ids = None

    new, out = apply_envelope_op(base_ledger, _FakeOp())  # type: ignore[arg-type]
    assert out.status is ApplyStatus.REJECTED
    assert "not_a_real_op" in out.message
    assert new is base_ledger
