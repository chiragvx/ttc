"""OpenRouterDeltaProvider: function-calling wiring + parsing, via an injected fake POST (no key/net)."""

from __future__ import annotations

import json

from packages.agents.openrouter_provider import OpenRouterDeltaProvider
from packages.ledger.deltas import ParameterDelta

SKIN = "instances.root.params.skin_thickness_mm"


def _tool_response(arguments):
    return {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "propose_parameter_delta", "arguments": arguments}}]}}]}


def test_parses_string_arguments_and_wires_forced_function_call():
    captured = {}

    def fake_post(*, url, headers, **kw):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = kw["json"]
        return _tool_response(json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 3.0}]}))

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "skin 3mm"}], ledger_json="{}")

    assert out.deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]
    assert captured["payload"]["tool_choice"] == {"type": "function", "function": {"name": "propose_parameter_delta"}}
    assert captured["headers"]["Authorization"] == "Bearer x"
    assert "deepseek" in captured["payload"]["model"]


def test_parses_feature_ops_round_trip():
    # feature_ops is just another field on the DeltaProposal model bound via
    # parameter_delta_tool_schema() — prove the tool-call round-trip preserves it unchanged rather
    # than assuming Pydantic deserialization "just works" (per the task's explicit ask).
    fake_feature_op = {
        "op": "add_feature", "instance_id": "root", "kind": "hole", "shape": "circle",
        "dia_mm": 92.0, "through": True, "x_mm": 0.0, "y_mm": 0.0,
        "rationale": "Stanley 40oz cup pass-through",
    }

    def fake_post(*, url, headers, **kw):
        return _tool_response(json.dumps({"deltas": [], "feature_ops": [fake_feature_op]}))

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "cut a hole"}], ledger_json="{}")

    assert len(out.feature_ops) == 1
    fop = out.feature_ops[0]
    assert fop.op == "add_feature"
    assert fop.instance_id == "root"
    assert fop.kind == "hole"
    assert fop.shape == "circle"
    assert fop.dia_mm == 92.0
    assert fop.through is True
    assert fop.rationale == "Stanley 40oz cup pass-through"


def test_parses_instance_ops_round_trip():
    # instance_ops is just another field on the DeltaProposal model bound via
    # parameter_delta_tool_schema() — prove the tool-call round-trip preserves it unchanged, same
    # verification pattern as test_parses_feature_ops_round_trip above.
    fake_instance_op = {
        "op": "add_instance", "subsystem_type": "enclosure", "instance_id": None,
        "parent_id": None, "x_mm": None, "y_mm": None, "z_mm": None,
        "rationale": "satellite body",
    }

    def fake_post(*, url, headers, **kw):
        return _tool_response(json.dumps({"deltas": [], "instance_ops": [fake_instance_op]}))

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "design a satellite"}],
                              ledger_json="{}")

    assert len(out.instance_ops) == 1
    iop = out.instance_ops[0]
    assert iop.op == "add_instance"
    assert iop.subsystem_type == "enclosure"
    assert iop.instance_id is None
    assert iop.x_mm is None and iop.y_mm is None and iop.z_mm is None
    assert iop.rationale == "satellite body"


def test_parses_dict_arguments():
    def fake_post(*, url, headers, **kw):
        return _tool_response({"deltas": [{"target_node": SKIN, "requested_value": 2.5}]})

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")
    assert out.deltas[0].requested_value == 2.5


def test_no_tool_call_fails_safe():
    def fake_post(*, url, headers, **kw):
        return {"choices": [{"message": {"content": "hi"}}]}

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")
    assert out.request_clarification is not None and not out.deltas


def test_missing_api_key_asks_for_it():
    prov = OpenRouterDeltaProvider(api_key="")  # no post injected, no key
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")
    assert "OPENROUTER_API_KEY" in (out.request_clarification or "")


def test_stream_chat_yields_tokens_then_proposal():
    # tool-call arguments fragmented across two chunks (the tricky streaming case)
    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {"content": "I'll set "}}]}
        yield {"choices": [{"delta": {"content": "the skin."}}]}
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"deltas":[{"target_node":"'}}]}}]}
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": SKIN + '","requested_value":3.0}]}'}}]}}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "skin 3mm"}], ledger_json="{}"))

    tokens = "".join(p for k, p in events if k == "token")
    assert tokens == "I'll set the skin."
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]
    assert events[-1] == ("done", None)


def test_stream_chat_no_key_errors():
    prov = OpenRouterDeltaProvider(api_key="")
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "x"}], ledger_json="{}"))
    assert events == [("error", "OPENROUTER_API_KEY is not set")]


def test_stream_chat_empty_turn_yields_error_not_silence():
    # a completion with no tool call and no content — under tool_choice="auto" a model is fully
    # entitled to produce this. Used to fall straight through to a single ("done", None) with zero
    # signal that anything went wrong (the direct mechanism behind a permanently-blank chat bubble);
    # must now yield an explicit error instead.
    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "do it"}], ledger_json="{}"))

    kinds = [k for k, _ in events]
    assert "error" in kinds
    assert "token" not in kinds
    assert "proposal" not in kinds
    assert events[-1] == ("done", None)


def test_stream_chat_malformed_tool_call_json_yields_error_not_silent_continue():
    # truncated/invalid JSON in the tool-call arguments (e.g. from hitting max_tokens mid-generation)
    # used to be a bare `except Exception: continue` — silently dropped, no log, no error event.
    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"deltas":[{"target_node":"'}}]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "??"}], ledger_json="{}"))

    errors = [msg for k, msg in events if k == "error"]
    assert errors and "could not be parsed" in errors[0]
    assert not any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def test_stream_chat_truncated_finish_reason_yields_error():
    # finish_reason == "length" (cut off by the max_tokens cap) must surface as an explicit error,
    # distinct from "the model chose not to act" — even though a real (well-formed) proposal DID
    # come through, the user should still be told the completion was truncated.
    delta_args = json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 3.0}]})

    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": delta_args}}]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "length"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "skin 3mm"}], ledger_json="{}"))

    errors = [msg for k, msg in events if k == "error"]
    assert any("cut off" in e for e in errors)
    assert any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def test_stream_chat_default_chat_max_tokens_higher_than_propose_delta():
    # the streaming/conversational path gets a higher cap than the single-shot delta-emitter path —
    # a multi-part proposal (several add_instance entries + deltas + rationale) needs more room.
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["max_tokens"] = json["max_tokens"]
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    assert captured["max_tokens"] > 1024
    assert captured["max_tokens"] == prov.chat_max_tokens
