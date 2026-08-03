"""DeltaProposal._repair_known_wire_quirks (packages/ledger/deltas.py) — a `model_validator(mode=
"before")` that tolerates two independently live-reproduced Qwen3.6-plus tool-call quirks (2026-07-27),
run BEFORE strict per-field validation. Mirrors tests/backend/test_scope_proposal.py's own
`_coerce_scope_proposal_string` coverage style: liberal at the wire, strict everywhere else — anything
the repair can't confidently redirect must still raise exactly as before, never silently dropped."""

from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from packages.ledger.deltas import DeltaProposal


# --- 1. A list field double-encoded as a JSON string ----------------------------------------------


def test_coerces_a_json_string_deltas_field():
    # 2026-07-27 live repro: 'deltas': '\n[{"requested_value": 800, ...}]\n' instead of a real array,
    # sinking an otherwise fully valid proposal (18 stacked errors traced back to this one field).
    encoded = json.dumps([
        {"target_node": "instances.top_shelf.params.width_mm", "requested_value": 600,
         "rationale": "cart footprint"},
    ])
    proposal = DeltaProposal.model_validate({"deltas": encoded})
    assert len(proposal.deltas) == 1
    assert proposal.deltas[0].target_node == "instances.top_shelf.params.width_mm"
    assert proposal.deltas[0].requested_value == 600


@pytest.mark.parametrize("field", ["feature_ops", "instance_ops", "connection_ops", "coupling_ops"])
def test_coerces_a_json_string_for_every_list_field(field):
    proposal = DeltaProposal.model_validate({field: "[]"})
    assert getattr(proposal, field) == []


def test_coerces_a_json_string_suggestions_field():
    proposal = DeltaProposal.model_validate({"suggestions": json.dumps(["a", "b"])})
    assert proposal.suggestions == ["a", "b"]


def test_still_rejects_a_genuinely_malformed_deltas_string():
    # the coercion must fall through to normal (strict) validation on a string that ISN'T valid JSON,
    # or that decodes to something other than a list — never silently swallow a real error.
    with pytest.raises(ValidationError):
        DeltaProposal.model_validate({"deltas": "not json at all"})


def test_still_rejects_a_deltas_string_that_decodes_to_a_non_list():
    with pytest.raises(ValidationError):
        DeltaProposal.model_validate({"deltas": json.dumps({"not": "a list"})})


# --- 2. A dimension field on add_instance/move_instance itself, instead of a separate delta -------


def test_redirects_an_extra_numeric_field_on_add_instance_into_a_synthesized_delta():
    # 2026-07-27 live repro: an add_instance for a flat_bar carried length_mm/width_mm/thickness_mm
    # directly on the op instead of as deltas — all three rejected by InstanceOp's extra="forbid".
    proposal = DeltaProposal.model_validate({
        "instance_ops": [{
            "op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "brace",
            "length_mm": 573, "width_mm": 12, "thickness_mm": 3, "x_mm": 0, "y_mm": 0, "z_mm": 0,
        }],
    })
    assert proposal.instance_ops[0].subsystem_type == "flat_bar"
    recovered = {d.target_node: d.requested_value for d in proposal.deltas}
    assert recovered == {
        "instances.brace.params.length_mm": 573,
        "instances.brace.params.width_mm": 12,
        "instances.brace.params.thickness_mm": 3,
    }


def test_redirected_deltas_are_appended_to_already_present_deltas_not_overwritten():
    proposal = DeltaProposal.model_validate({
        "deltas": [{"target_node": "instances.other.params.height_mm", "requested_value": 5}],
        "instance_ops": [{
            "op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "brace",
            "length_mm": 573,
        }],
    })
    targets = {d.target_node for d in proposal.deltas}
    assert targets == {"instances.other.params.height_mm", "instances.brace.params.length_mm"}


def test_redirects_an_extra_field_on_move_instance_too():
    proposal = DeltaProposal.model_validate({
        "instance_ops": [{
            "op": "move_instance", "instance_id": "brace",
            "x_mm": 0, "y_mm": 0, "z_mm": 10, "width_mm": 12,
        }],
    })
    assert proposal.deltas[0].target_node == "instances.brace.params.width_mm"


def test_does_not_redirect_an_extra_field_on_remove_instance():
    # remove_instance never carries dimensions in practice; nothing to recover, so the extra field
    # must still be rejected normally rather than silently vanishing.
    with pytest.raises(ValidationError):
        DeltaProposal.model_validate({
            "instance_ops": [{"op": "remove_instance", "instance_id": "brace", "length_mm": 573}],
        })


def test_does_not_redirect_when_instance_id_is_missing():
    # can't safely target a delta without knowing which instance it belongs to (add_instance may
    # auto-generate the id at apply time) — never guess it, leave the op's own error to surface.
    with pytest.raises(ValidationError):
        DeltaProposal.model_validate({
            "instance_ops": [{"op": "add_instance", "subsystem_type": "flat_bar", "length_mm": 573}],
        })


def test_does_not_redirect_a_non_numeric_extra_field():
    with pytest.raises(ValidationError):
        DeltaProposal.model_validate({
            "instance_ops": [{
                "op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "brace",
                "material": "steel",
            }],
        })


def test_a_legitimate_add_instance_with_no_extra_fields_is_unaffected():
    proposal = DeltaProposal.model_validate({
        "instance_ops": [{"op": "add_instance", "subsystem_type": "bracket", "instance_id": "b1"}],
    })
    assert proposal.instance_ops[0].instance_id == "b1"
    assert proposal.deltas == []
