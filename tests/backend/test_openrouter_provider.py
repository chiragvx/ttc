"""OpenRouterDeltaProvider: function-calling wiring + parsing, via an injected fake POST (no key/net)."""

from __future__ import annotations

import json

from packages.agents.openrouter_provider import OpenRouterDeltaProvider
from packages.ledger.deltas import ParameterDelta

SKIN = "domains.structure.skin_thickness_mm"


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
