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
