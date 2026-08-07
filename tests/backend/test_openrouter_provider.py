"""OpenRouterDeltaProvider: function-calling wiring + parsing, via an injected fake POST (no key/net)."""

from __future__ import annotations

import importlib.util
import json

import pytest

import packages.agents.openrouter_provider as openrouter_provider
from packages.agents.openrouter_provider import (
    OpenRouterDeltaProvider,
    _extract_json_values,
    _looks_truncated,
    _strict_schema,
    model_supports_vision,
)
from packages.ledger.deltas import ParameterDelta, parameter_delta_tool_schema

SKIN = "instances.root.params.skin_thickness_mm"


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeHTTPStatusError(Exception):
    """Stands in for httpx.HTTPStatusError (same `.response.status_code` shape) without needing a
    real httpx exception — propose_delta's retry check is duck-typed for exactly this reason."""

    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.response = _FakeResponse(status_code)


def _decode_error(args: str) -> json.JSONDecodeError:
    try:
        json.loads(args)
    except json.JSONDecodeError as e:
        return e
    raise AssertionError(f"expected {args!r} to fail to parse")


def test_looks_truncated_true_for_an_unterminated_string_regardless_of_position():
    # pos points at the string's OPENING quote for this error type, which can sit far from len(args)
    # even though EOF-mid-string is definitionally always a cut-off stream.
    args = '{"deltas":[{"target_node":"instances.root.params.'
    assert _looks_truncated(args, _decode_error(args)) is True


def test_looks_truncated_true_when_the_error_lands_exactly_at_the_end():
    args = '{"deltas":[{"target_node":"x","requested_value":3'  # missing closing braces
    assert _looks_truncated(args, _decode_error(args)) is True


def test_looks_truncated_false_for_a_mid_string_syntax_error_with_trailing_content():
    args = '{"deltas": [{"target_node": "x", "requested_value": }]}'  # missing value, then more JSON
    assert _looks_truncated(args, _decode_error(args)) is False


def _assert_every_object_node_is_strict(node) -> None:
    """Recursively walk a `_strict_schema()` output and assert every object-shaped node (a dict with
    a "properties" key) has "required" == sorted(its own property names) and "additionalProperties"
    is False -- mirrors `_strict_schema`'s OWN recursion rules ($defs / properties / items /
    anyOf|oneOf|allOf) so this check is exhaustive over the real schema, not a spot-check of one or
    two hand-picked fields."""
    if not isinstance(node, dict):
        return
    if isinstance(node.get("properties"), dict):
        assert node["required"] == sorted(node["properties"].keys()), \
            f"required != sorted(properties) for node titled {node.get('title')!r}: {node}"
        assert node["additionalProperties"] is False, f"additionalProperties not closed: {node}"
        for prop_schema in node["properties"].values():
            _assert_every_object_node_is_strict(prop_schema)
    if isinstance(node.get("$defs"), dict):
        for def_schema in node["$defs"].values():
            _assert_every_object_node_is_strict(def_schema)
    if "items" in node:
        _assert_every_object_node_is_strict(node["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        for branch in node.get(key) or []:
            _assert_every_object_node_is_strict(branch)


def test_strict_schema_makes_every_property_required_and_closes_every_object_exhaustively():
    # Against the REAL schema (12 object types across $defs + the root DeltaProposal), not a
    # synthetic toy -- this is what actually gets sent to OpenRouter.
    original = parameter_delta_tool_schema()
    transformed = _strict_schema(original)

    _assert_every_object_node_is_strict(transformed)
    # a few concrete objects that must all have been visited, so the exhaustive walk above isn't
    # silently vacuous (e.g. because "properties" was renamed/missing and the walk found nothing)
    assert transformed["required"] == sorted(transformed["properties"].keys())
    assert transformed["$defs"]["FitOp"]["required"] == sorted(transformed["$defs"]["FitOp"]["properties"].keys())
    assert "id" in transformed["$defs"]["FitOp"]["required"]  # a previously-optional field, now required


def test_strict_schema_never_mutates_the_caller_schema():
    original = parameter_delta_tool_schema()
    before = json.dumps(original, sort_keys=True)
    _strict_schema(original)
    assert json.dumps(original, sort_keys=True) == before


def test_strict_schema_preserves_defaults_enums_and_leaves_non_object_defs_untouched():
    transformed = _strict_schema(parameter_delta_tool_schema())
    delta = transformed["$defs"]["ParameterDelta"]
    assert delta["properties"]["source"]["default"] == "unsourced"
    assert delta["properties"]["source"]["enum"] == \
        ["verified", "rule_derived", "solver_validated", "unsourced"]
    # LockState is a bare enum $def (no "properties") -- never touched by the transform
    lock_state = transformed["$defs"]["LockState"]
    assert lock_state["enum"] == ["DYNAMIC", "HARD_LOCK"]
    assert "required" not in lock_state
    assert "additionalProperties" not in lock_state


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


def test_propose_delta_first_attempt_is_bound_to_a_strict_transformed_tool_schema():
    # 2026-08-04: propose_delta's FIRST attempt is now a strict, grammar-constrained tool schema --
    # eliminates the "dropped comma in a large free-generated JSON blob" failure class by
    # construction, rather than only detecting/recovering from it after the fact.
    captured = {}

    def fake_post(*, url, headers, **kw):
        captured["payload"] = kw["json"]
        return _tool_response(json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 3.0}]}))

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    prov.propose_delta(system="", conversation=[{"role": "user", "content": "skin 3mm"}], ledger_json="{}")

    tool = captured["payload"]["tools"][0]
    assert tool["function"]["strict"] is True
    params = tool["function"]["parameters"]
    # the transform actually ran: spot-check a couple of nested optional fields are now required
    assert params["required"] == sorted(params["properties"].keys())
    connection_op = params["$defs"]["ConnectionOp"]
    assert "a_instance" in connection_op["required"] and "kind" in connection_op["required"]
    fit_op = params["$defs"]["FitOp"]
    assert "clearance_mm" in fit_op["required"]


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


def test_propose_delta_recovers_from_trailing_junk_after_a_valid_json_value():
    # Same failure class stream_chat already recovers from (2026-07-19 live repro:
    # test_stream_chat_recovers_a_complete_payload_with_trailing_junk): a complete, valid tool-call
    # `arguments` string followed by trailing non-JSON junk must not be thrown away wholesale via a
    # bare json.loads.
    good = json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 4.0}]})
    args = good + "\nsome trailing junk here"

    def fake_post(*, url, headers, **kw):
        return _tool_response(args)

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "skin 4mm"}], ledger_json="{}")

    assert out.deltas == [ParameterDelta(target_node=SKIN, requested_value=4.0)]


def test_propose_delta_prefers_the_last_duplicate_tool_call_when_the_first_is_invalid():
    # 2026-07-23-style live repro (see test_stream_chat_recovers_the_later_valid_draft_over_an_
    # earlier_invalid_one): a model can double-emit the forced propose_parameter_delta tool call —
    # an abandoned, wrongly-shaped draft first (deltas as "key=value" strings, not the real
    # ParameterDelta schema), then a complete, correctly-shaped proposal second. The stale FIRST
    # entry must not shadow the later good one.
    bad_call = {"function": {"name": "propose_parameter_delta",
                              "arguments": json.dumps({"deltas": ["instances.root.params.skin_thickness_mm=3.0"]})}}
    good_call = {"function": {"name": "propose_parameter_delta",
                              "arguments": json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 5.0}]})}}

    def fake_post(*, url, headers, **kw):
        return {"choices": [{"message": {"tool_calls": [bad_call, good_call]}}]}

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "skin 5mm"}], ledger_json="{}")

    assert out.deltas == [ParameterDelta(target_node=SKIN, requested_value=5.0)]


def test_propose_delta_prefers_the_last_duplicate_tool_call_even_when_both_validate():
    # Not just "fall back to the second when the first is broken" — literally prefer the LAST
    # validating entry, mirroring stream_chat's own "prefer the later candidate" rule.
    first_call = {"function": {"name": "propose_parameter_delta",
                                "arguments": json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 1.0}]})}}
    second_call = {"function": {"name": "propose_parameter_delta",
                                 "arguments": json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 2.0}]})}}

    def fake_post(*, url, headers, **kw):
        return {"choices": [{"message": {"tool_calls": [first_call, second_call]}}]}

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")

    assert out.deltas == [ParameterDelta(target_node=SKIN, requested_value=2.0)]


def test_propose_delta_retries_on_429_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_post(*, url, headers, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _FakeHTTPStatusError(429)
        return _tool_response(json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 6.0}]}))

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post, sleep=sleeps.append)
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "skin 6mm"}], ledger_json="{}")

    assert calls["n"] == 3  # 2 failed attempts + 1 that succeeded
    assert out.deltas == [ParameterDelta(target_node=SKIN, requested_value=6.0)]
    assert sleeps == [0.5, 1.0]  # exponential backoff between the 2 failed attempts


def test_propose_delta_retries_on_a_5xx_and_on_a_timeout_too():
    # 429 is one retryable class; a bare 5xx and a request-timeout-shaped exception (duck-typed on
    # the class name, mirroring httpx.TimeoutException/ConnectTimeout/ReadTimeout) are the other two
    # named in the retry contract.
    for exc in (_FakeHTTPStatusError(503), type("ReadTimeout", (Exception,), {})("timed out")):
        calls = {"n": 0}

        def fake_post(*, url, headers, _exc=exc, **kw):
            calls["n"] += 1
            if calls["n"] < 2:
                raise _exc
            return _tool_response(json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 7.0}]}))

        prov = OpenRouterDeltaProvider(api_key="x", post=fake_post, sleep=lambda s: None)
        out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")
        assert out.deltas == [ParameterDelta(target_node=SKIN, requested_value=7.0)]
        assert calls["n"] == 2


def test_propose_delta_gives_up_after_exhausting_retries_on_a_persistent_429():
    # bounded, not unlimited: a request that NEVER succeeds must stop after the fixed attempt budget
    # and propagate the transport error, rather than retry forever.
    calls = {"n": 0}

    def fake_post(*, url, headers, **kw):
        calls["n"] += 1
        raise _FakeHTTPStatusError(429)

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post, sleep=lambda s: None)
    try:
        prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")
        raise AssertionError("expected the persistent 429 to propagate once retries are exhausted")
    except _FakeHTTPStatusError:
        pass
    assert calls["n"] == 3  # exactly the bounded attempt budget, not unlimited


def test_propose_delta_does_not_retry_a_non_retryable_error():
    # a 400 (bad request) is a caller-side error retrying can never fix — must propagate immediately,
    # with no backoff sleep and no wasted extra attempt.
    #
    # UPDATED 2026-08-04: calls["n"] is now genuinely 2, not 1 — NEW, INTENDED behavior, not a
    # loosened bound. propose_delta's first attempt now uses a STRICT tool schema; a 400 there is
    # ambiguous between "genuinely bad request" and "this model/provider rejects strict schemas", so
    # it gets exactly ONE fallback attempt against the ORIGINAL plain (unconstrained) schema — see
    # test_propose_delta_falls_back_to_a_plain_schema_and_still_propagates_if_that_also_fails just
    # below for the dedicated test of this exact path (this fake_post rejects BOTH attempts with a
    # 400, so the final exception still propagates immediately either way, with no sleep and no
    # retry-loop attempt beyond the one intentional fallback — the "no wasted extra attempt" contract
    # this test's own comment describes is preserved, just against a budget of 2 instead of 1).
    calls = {"n": 0}

    def fake_post(*, url, headers, **kw):
        calls["n"] += 1
        raise _FakeHTTPStatusError(400)

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post, sleep=lambda s: (_ for _ in ()).throw(
        AssertionError("should not sleep/retry on a non-retryable error")))
    try:
        prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")
        raise AssertionError("expected the non-retryable 400 to propagate immediately")
    except _FakeHTTPStatusError:
        pass
    assert calls["n"] == 2  # 1 strict attempt + 1 plain fallback attempt, both non-retryable 400s


def test_propose_delta_falls_back_to_a_plain_schema_after_a_strict_400_then_succeeds():
    calls = []

    def fake_post(*, url, headers, **kw):
        calls.append(kw["json"])
        if len(calls) == 1:
            raise _FakeHTTPStatusError(400)
        return _tool_response(json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 9.0}]}))

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post, sleep=lambda s: (_ for _ in ()).throw(
        AssertionError("should not sleep on a strict-schema fallback — it is not a transport retry")))
    out = prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")

    assert out.deltas == [ParameterDelta(target_node=SKIN, requested_value=9.0)]
    assert len(calls) == 2
    assert calls[0]["tools"][0]["function"]["strict"] is True
    assert "strict" not in calls[1]["tools"][0]["function"]  # the fallback attempt is the plain shape


def test_propose_delta_falls_back_to_a_plain_schema_and_still_propagates_if_that_also_fails():
    calls = []

    def fake_post(*, url, headers, **kw):
        calls.append(kw["json"])
        raise _FakeHTTPStatusError(400)

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post, sleep=lambda s: (_ for _ in ()).throw(
        AssertionError("should not sleep on a non-retryable error")))
    try:
        prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")
        raise AssertionError("expected the 400-then-400 to still propagate")
    except _FakeHTTPStatusError as e:
        assert e.response.status_code == 400
    assert len(calls) == 2
    assert calls[0]["tools"][0]["function"]["strict"] is True
    assert "strict" not in calls[1]["tools"][0]["function"]


def test_propose_delta_a_persistent_429_never_falls_back_to_a_plain_schema():
    # 429 is retryable transport noise, not a schema complaint -- a different schema shape can't fix
    # a rate limit, so it must NEVER trigger the strict->plain fallback on top of the existing
    # transport-retry budget (_PROPOSE_DELTA_RETRY_ATTEMPTS), which _do_post_with_retry already
    # exhausts on its own.
    from packages.agents.openrouter_provider import _PROPOSE_DELTA_RETRY_ATTEMPTS

    calls = []

    def fake_post(*, url, headers, **kw):
        calls.append(kw["json"])
        raise _FakeHTTPStatusError(429)

    prov = OpenRouterDeltaProvider(api_key="x", post=fake_post, sleep=lambda s: None)
    try:
        prov.propose_delta(system="", conversation=[{"role": "user", "content": "x"}], ledger_json="{}")
        raise AssertionError("expected the persistent 429 to propagate once retries are exhausted")
    except _FakeHTTPStatusError:
        pass

    # exactly the pre-existing transport-retry budget -- the fallback logic added NO extra attempt
    assert len(calls) == _PROPOSE_DELTA_RETRY_ATTEMPTS
    # the plain (non-strict) shape never appeared in any captured payload -- no fallback was attempted
    assert all(c["tools"][0]["function"].get("strict") is True for c in calls)


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


def test_stream_chat_first_attempt_is_bound_to_a_strict_transformed_tool_schema():
    # 2026-08-04: same strict-schema-first fix as propose_delta, applied per streaming round.
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["payload"] = json
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    tool = captured["payload"]["tools"][0]
    assert tool["function"]["name"] == "propose_parameter_delta"
    assert tool["function"]["strict"] is True
    params = tool["function"]["parameters"]
    assert params["required"] == sorted(params["properties"].keys())
    feature_op = params["$defs"]["FeatureOp"]
    assert "shape" in feature_op["required"] and "kind" in feature_op["required"]


def test_stream_chat_falls_back_to_a_plain_schema_after_a_strict_400_then_succeeds():
    calls = []
    delta_args = json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 9.0}]})

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            raise _FakeHTTPStatusError(400)
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": delta_args}}]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "x"}], ledger_json="{}"))

    assert not any(k == "error" for k, _ in events)
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=9.0)]
    assert len(calls) == 2
    assert calls[0]["tools"][0]["function"]["strict"] is True
    assert "strict" not in calls[1]["tools"][0]["function"]  # the fallback attempt is the plain shape
    assert events[-1] == ("done", None)


def test_stream_chat_falls_back_to_a_plain_schema_and_still_errors_if_that_also_fails():
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        raise _FakeHTTPStatusError(400)

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "x"}], ledger_json="{}"))

    assert len(calls) == 2  # 1 strict attempt + 1 plain fallback attempt, both 400
    assert calls[0]["tools"][0]["function"]["strict"] is True
    assert "strict" not in calls[1]["tools"][0]["function"]
    # a genuine failure still gets the SAME ('error', ...) then ('done', None) contract stream_chat
    # has always used for a transport-level exception — the fallback machinery doesn't change that.
    errors = [msg for k, msg in events if k == "error"]
    assert len(errors) == 1 and "HTTP 400" in errors[0]
    assert not any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def test_stream_chat_a_429_never_falls_back_to_a_plain_schema():
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        raise _FakeHTTPStatusError(429)

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "x"}], ledger_json="{}"))

    # no fallback attempt at all -- 429 is excluded from the fallback condition, and stream_chat's
    # own streaming path has no separate transport-retry budget of its own to exhaust first either.
    assert len(calls) == 1
    assert calls[0]["tools"][0]["function"]["strict"] is True
    errors = [msg for k, msg in events if k == "error"]
    assert len(errors) == 1 and "HTTP 429" in errors[0]
    assert not any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def test_stream_chat_truncated_malformed_json_yields_only_the_cutoff_error_not_both():
    # 2026-07-19 live repro: a multi-part build request ("plenum + flange + 4 runners") with a long
    # prose plan ahead of the tool call (prose and the tool-call JSON share ONE token budget under
    # tool_choice="auto") truncated mid-tool-call-JSON — confirmed in the server log ("unterminated
    # string starting at: line 1 column 821"). Before this fix, that produced BOTH the generic
    # "could not be parsed — try rephrasing" error (misleading — rephrasing an equally-large request
    # would truncate again) AND the accurate "cut off... try a shorter or simpler request" error.
    # Only the actionable one should surface.
    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {"content": "Here's the plan: ..."}}]}
        tool_call = {"index": 0, "function": {
            "arguments": '{"instance_ops":[{"op":"add_instance","subsystem_type":"'}}
        yield {"choices": [{"delta": {"tool_calls": [tool_call]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "length"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "build the manifold"}], ledger_json="{}"))

    errors = [msg for k, msg in events if k == "error"]
    assert len(errors) == 1
    assert "cut off" in errors[0]
    assert "could not be parsed" not in errors[0]
    assert not any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def test_stream_chat_recovers_a_complete_payload_with_trailing_junk():
    # 2026-07-19 live repro: a complete, valid ~10KB tool call followed by ~35 bytes of something else
    # ("Extra data: line 2 column 1", finish_reason=="tool_calls" -- a NORMAL completion, not a
    # cutoff). json.loads demands the whole string be one JSON value and threw the real, complete
    # proposal away over trailing transport noise. Must now recover the valid prefix instead.
    good = json.dumps({"instance_ops": [
        {"op": "add_instance", "subsystem_type": "bulkhead_frame", "instance_id": "top_ring"}]})
    args = good + "\nsome trailing junk here"

    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": args}}]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "do it"}], ledger_json="{}"))

    assert not any(k == "error" for k, _ in events)
    proposals = [p for k, p in events if k == "proposal"]
    assert len(proposals) == 1
    assert proposals[0].instance_ops[0].instance_id == "top_ring"
    assert events[-1] == ("done", None)


def test_extract_json_values_returns_one_value_with_trailing_non_json_junk():
    good = {"instance_ops": [{"op": "add_instance", "subsystem_type": "bracket"}]}
    values = _extract_json_values(json.dumps(good) + "\nsome trailing junk here")
    assert len(values) == 1
    assert values[0][0] == good


def test_extract_json_values_returns_every_complete_value_found_back_to_back():
    # 2026-07-23 live repro (Qwen3.6-plus): a model second-guessed itself mid-generation and emitted
    # TWO complete JSON objects into one tool call's arguments -- an abandoned draft immediately
    # followed by a complete one. The old single-raw_decode recovery only ever surfaced the first.
    first = {"request_clarification": "need more info"}
    second = {"instance_ops": [{"op": "add_instance", "subsystem_type": "bracket"}]}
    values = _extract_json_values(json.dumps(first) + json.dumps(second))
    assert [v for v, _ in values] == [first, second]


def test_extract_json_values_returns_empty_for_genuinely_malformed_json():
    # a syntax error INSIDE the structure (not at the very start) must yield zero values -- this is
    # what keeps the recovery path from ever masking a real parse failure or a truncation.
    values = _extract_json_values('{"instance_ops": [{"op": }]}')
    assert values == []


def test_stream_chat_recovers_the_later_valid_draft_over_an_earlier_invalid_one():
    # 2026-07-23 live repro: the model emitted an abandoned, WRONGLY-shaped draft first (deltas as
    # "key=value" strings instead of the real ParameterDelta schema), then a complete, correctly
    # shaped proposal second -- both inside the SAME tool call. The old recovery kept only the first
    # complete JSON value found, which happened to be the bad draft, and threw the good one away as
    # "trailing junk" -- reporting "could not be parsed" over a proposal that was actually fine.
    bad_draft = json.dumps({"deltas": ["instances.root.params.skin_thickness_mm=3.0"]})
    good_draft = json.dumps({"instance_ops": [{"op": "add_instance", "subsystem_type": "bracket", "instance_id": "root"}]})
    args = bad_draft + good_draft

    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": args}}]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "add a bracket"}], ledger_json="{}"))

    assert not any(k == "error" for k, _ in events)
    proposals = [p for k, p in events if k == "proposal"]
    assert len(proposals) == 1
    assert proposals[0].instance_ops[0].instance_id == "root"
    assert proposals[0].deltas == []  # the bad draft's malformed deltas were correctly discarded


def test_stream_chat_genuinely_truncated_json_is_not_falsely_recovered():
    # raw_decode must fail identically to json.loads on a GENUINELY incomplete value (no complete
    # top-level object exists anywhere in the string) -- the recovery path must never mask a real
    # truncation.
    def fake_stream(*, url, headers, json):
        tool_call = {"index": 0, "function": {
            "arguments": '{"instance_ops":[{"op":"add_instance","subsystem_type":"'}}
        yield {"choices": [{"delta": {"tool_calls": [tool_call]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "length"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "do it"}], ledger_json="{}"))

    errors = [msg for k, msg in events if k == "error"]
    assert len(errors) == 1 and "cut off" in errors[0]
    assert not any(k == "proposal" for k, _ in events)


def test_stream_chat_yields_a_proposal_for_scope_connection_or_coupling_ops_alone():
    # 2026-07-19 review (HIGH): the proposal-yield gate's OR-chain listed deltas/feature_ops/
    # instance_ops/request_clarification/suggestions but omitted connection_ops, coupling_ops, AND
    # scope_proposal — a tool call whose ONLY populated field was one of those three was silently
    # dropped, never reaching app.py's /chat SSE handler, with no error (a fully silent turn if the
    # model also emitted no prose). This was a PRE-EXISTING gap for connection_ops/coupling_ops
    # (Phase 1b/2b), only surfaced when Phase 5 added a fourth omitted field and a review caught the
    # whole pattern. One case per field, each with every other DeltaProposal field empty.
    for field, payload in (
        ("connection_ops", {"connection_ops": [{"op": "add_connection", "a_instance": "a", "a_interface": "root",
                                                 "b_instance": "b", "b_interface": "tip_right"}]}),
        ("coupling_ops", {"coupling_ops": [{"op": "add_coupling", "target_instance": "crank",
                                            "relation": "force_from_pressure_area", "inputs": []}]}),
        ("scope_proposal", {"scope_proposal": {"goal": "make a drone", "parts": [
            {"subsystem_type": "bracket", "role": "frame"}]}}),
    ):
        arguments = json.dumps({"deltas": [], **payload})

        def fake_stream(*, url, headers, json, _arguments=arguments):
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": _arguments}}]}}]}

        prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
        events = list(prov.stream_chat(messages=[{"role": "user", "content": "do it"}], ledger_json="{}"))
        proposals = [p for k, p in events if k == "proposal"]
        assert proposals, f"{field}-only proposal was dropped by the yield gate"
        assert getattr(proposals[0], field), f"{field} was empty on the yielded proposal"


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
    # invalid JSON in the tool-call arguments that is NOT truncation-shaped (the syntax error sits in
    # the MIDDLE of the string, with more content after it — a missing value, not a cut-off stream)
    # used to be a bare `except Exception: continue` — silently dropped, no log, no error event.
    def fake_stream(*, url, headers, json):
        tool_call = {"index": 0, "function": {
            "arguments": '{"deltas": [{"target_node": "x", "requested_value": }]}'}}
        yield {"choices": [{"delta": {"tool_calls": [tool_call]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "??"}], ledger_json="{}"))

    errors = [msg for k, msg in events if k == "error"]
    # foundations-audit follow-up (2026-07-21, live-reproduced): this assertion used to check ONLY
    # errors[0]'s content, never the COUNT — which let a real double-error bug hide in plain sight
    # (this exact repro also yielded a second, redundant "no response was generated" error underneath
    # the specific one, since the generic end-of-stream fallback didn't know a specific error had
    # already fired). Asserting the count is what actually would have caught it.
    assert len(errors) == 1
    assert "could not be parsed" in errors[0]
    assert not any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def test_stream_chat_schema_invalid_tool_call_yields_exactly_one_error_not_two():
    """foundations-audit follow-up (2026-07-21, live-reproduced): a tool call whose arguments are
    VALID JSON but the WRONG SHAPE (a bare list, not the DeltaProposal object) hits a genuinely
    different code path than malformed-JSON-syntax above (schema validation, not json.loads) — but
    had the identical bug: the per-call "could not be parsed" error AND the generic end-of-stream
    "no response was generated" fallback both fired for the same turn, since nothing had set
    saw_proposal/saw_token and the fallback didn't know a specific error already covered it."""
    def fake_stream(url, headers, json):
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "[1, 2, 3]"}}]}, "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    errors = [msg for k, msg in events if k == "error"]
    assert len(errors) == 1
    assert "could not be parsed" in errors[0]
    assert not any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def test_stream_chat_json_error_at_end_of_string_is_treated_as_truncation_even_without_finish_reason_length():
    # 2026-07-19 live repro #2: a SECOND real "8 runners" build still truncated mid-tool-call-JSON at
    # the raised 6144-token cap, but the raw OpenRouter/DeepSeek stream never surfaced
    # finish_reason=="length" for it — finish_reason alone was not a reliable truncation signal for
    # this real provider/model combination, so the misleading "could not be parsed" message still
    # showed. A JSON syntax error positioned at (or right at) the END of the accumulated arg string —
    # e.g. an unterminated string, exactly what a cut-off stream produces — is itself
    # provider-independent evidence of truncation and must get the accurate "cut off" message, even
    # when finish_reason claims "stop".
    def fake_stream(*, url, headers, json):
        tool_call = {"index": 0, "function": {
            "arguments": '{"deltas":[{"target_node":"instances.root.params.'}}
        yield {"choices": [{"delta": {"tool_calls": [tool_call]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "build the manifold"}], ledger_json="{}"))

    errors = [msg for k, msg in events if k == "error"]
    assert len(errors) == 1
    assert "cut off" in errors[0]
    assert "could not be parsed" not in errors[0]
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


def test_stream_chat_unrecognized_finish_reason_with_a_valid_proposal_yields_no_spurious_cutoff():
    """foundations-audit follow-up (2026-07-21, live-reproduced): the old check was `finish_reason
    not in (None, "stop", "tool_calls")` — a BLACKLIST. OpenRouter proxies many backend models, each
    free to report its own terminal-state string ("eos", a legacy "function_call", a proxy quirk);
    any of those got blanket-treated as truncation even when the tool call parsed AND validated
    cleanly. That produced a self-contradiction: a fully successful, ALREADY-APPLIED proposal (real
    geometry mutated) landing next to "the response was cut off — try a shorter or simpler request"
    in the same turn, which reads as "your edit failed" when it didn't, and invites a user to retry
    an already-applied edit. Only "length"/"content_filter" (unambiguous, well-known signals that
    content is genuinely missing) may still override a successfully-parsed proposal — see
    test_stream_chat_truncated_finish_reason_yields_error just above, which this must NOT break."""
    delta_args = json.dumps({"deltas": [{"target_node": SKIN, "requested_value": 3.0}]})

    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": delta_args}}]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "eos"}]}  # unrecognized, not a known-good/bad reason

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "skin 3mm"}], ledger_json="{}"))

    assert not any(k == "error" for k, _ in events)  # no spurious cutoff alongside the real success
    assert any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def test_stream_chat_unrecognized_finish_reason_with_no_proposal_still_yields_cutoff():
    """The fallback direction: an unrecognized finish_reason with NOTHING that validated is still the
    safest guess when there's no positive evidence the completion actually succeeded (mirrors the
    existing "no response was generated" backstop, just via the finish_reason-suspicious path)."""
    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {}, "finish_reason": "eos"}]}  # no tool call at all

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "skin 3mm"}], ledger_json="{}"))

    errors = [msg for k, msg in events if k == "error"]
    assert any("cut off" in e for e in errors)
    assert not any(k == "proposal" for k, _ in events)
    assert events[-1] == ("done", None)


def _fake_research_provider(result):
    """A minimal stand-in for `get_research_provider()`'s return value — only `.research(query)` is
    ever called on it."""
    class _Fake:
        def research(self, query):
            return result
    return _Fake()


def test_stream_chat_calls_research_tool_alone_then_continues_with_the_result(monkeypatch):
    # The model calls research_reference ALONE in round 1 (no propose_parameter_delta yet) -- it
    # should get the finding fed back as a tool result and a SECOND completion request to finalize.
    from packages.agents.research_provider import ResearchFinding
    finding = ResearchFinding(
        query="adjustable laptop stand",
        summary="uses a riser/hinge mechanism, not a rigid table",
        suggested_subsystem_types=["hinge"],
    )
    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: True)
    monkeypatch.setattr("packages.agents.openrouter_provider.get_research_provider",
                         lambda: _fake_research_provider(finding))

    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "research_reference", "arguments": '{"query":"adjustable laptop stand"}'}}]},
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"content": "Building it now."}}]}
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "make an adjustable laptop stand"}], ledger_json="{}"))

    assert len(calls) == 2  # the continuation round actually happened
    assert [p for k, p in events if k == "research"] == [finding]
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]

    round2_messages = calls[1]["messages"]
    assistant_msg = next(m for m in round2_messages if m.get("role") == "assistant" and m.get("tool_calls"))
    assert assistant_msg["tool_calls"][0] == {
        "id": "call_1", "type": "function",
        "function": {"name": "research_reference", "arguments": '{"query":"adjustable laptop stand"}'},
    }
    tool_msg = next(m for m in round2_messages if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "call_1"
    assert "riser/hinge" in tool_msg["content"]


def test_stream_chat_mixed_research_and_propose_in_same_round_does_not_continue(monkeypatch):
    # The model can also call BOTH tools in the SAME round -- propose_parameter_delta is
    # self-contained (no tool result to feed back), so this must be treated as final: research is
    # still executed/surfaced for display, but there is no second completion request.
    from packages.agents.research_provider import ResearchFinding
    finding = ResearchFinding(query="q", summary="s")
    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: True)
    monkeypatch.setattr("packages.agents.openrouter_provider.get_research_provider",
                         lambda: _fake_research_provider(finding))

    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {"name": "research_reference", "arguments": '{"query":"q"}'}},
            {"index": 1, "id": "call_2", "function": {
                "name": "propose_parameter_delta",
                "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}},
        ]}, "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "x"}], ledger_json="{}"))

    assert len(calls) == 1  # no continuation round
    assert [p for k, p in events if k == "research"] == [finding]
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]


def test_stream_chat_omits_research_tool_when_not_configured(monkeypatch):
    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: False)
    # read_subsystem_source defaults to ON (2026-08-06) -- disabled here so this test isolates
    # research_reference's OWN gate exactly as it did before that tool existed.
    monkeypatch.setattr("packages.agents.openrouter_provider.read_subsystem_source_enabled", lambda: False)
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["tools"] = json["tools"]
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    assert [t["function"]["name"] for t in captured["tools"]] == ["propose_parameter_delta"]


def test_stream_chat_offers_research_tool_when_configured(monkeypatch):
    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: True)
    # Isolated from read_subsystem_source's own (independent, default-on) gate -- see the comment on
    # test_stream_chat_omits_research_tool_when_not_configured just above.
    monkeypatch.setattr("packages.agents.openrouter_provider.read_subsystem_source_enabled", lambda: False)
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["tools"] = json["tools"]
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    names = {t["function"]["name"] for t in captured["tools"]}
    assert names == {"propose_parameter_delta", "research_reference"}


def test_stream_chat_omits_read_subsystem_source_tool_when_disabled(monkeypatch):
    monkeypatch.setattr("packages.agents.openrouter_provider.read_subsystem_source_enabled", lambda: False)
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["tools"] = json["tools"]
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    assert [t["function"]["name"] for t in captured["tools"]] == ["propose_parameter_delta"]


def test_stream_chat_offers_read_subsystem_source_tool_by_default():
    # No monkeypatch at all -- read_subsystem_source_enabled() is DEFAULT-ON (unlike research, which
    # defaults off), so it must appear alongside propose_parameter_delta with zero configuration.
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["tools"] = json["tools"]
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    names = {t["function"]["name"] for t in captured["tools"]}
    assert names == {"propose_parameter_delta", "read_subsystem_source"}


def test_stream_chat_research_returning_none_still_continues_without_a_research_event(monkeypatch):
    # A failed/empty lookup must never be silently dropped -- the model still needs an answer to
    # the tool call it made -- but must also never masquerade as a real finding (no 'research' event).
    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: True)
    monkeypatch.setattr("packages.agents.openrouter_provider.get_research_provider",
                         lambda: _fake_research_provider(None))

    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1",
                 "function": {"name": "research_reference", "arguments": '{"query":"q"}'}}]},
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "x"}], ledger_json="{}"))

    assert len(calls) == 2
    assert not any(k == "research" for k, _ in events)
    tool_msg = next(m for m in calls[1]["messages"] if m.get("role") == "tool")
    assert "no reference results" in tool_msg["content"]
    assert any(k == "proposal" for k, _ in events)


def test_stream_chat_caps_at_the_max_tool_rounds_bound(monkeypatch):
    # If every round ALSO comes back continuation-only (no propose_parameter_delta), the loop must
    # never exceed _MAX_TOOL_ROUNDS completion requests -- a hard cap, not a "keep going until
    # satisfied" loop. Asserted against the real constant (not a hardcoded literal) so this test
    # stays correct if the cap is retuned again later, same as it was bounded (at 2) before this
    # phase raised it to 4.
    from packages.agents.openrouter_provider import _MAX_TOOL_ROUNDS
    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: True)
    monkeypatch.setattr("packages.agents.openrouter_provider.get_research_provider",
                         lambda: _fake_research_provider(None))

    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": f"call_{len(calls)}",
             "function": {"name": "research_reference", "arguments": '{"query":"q"}'}}]},
            "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "x"}], ledger_json="{}"))

    assert len(calls) == _MAX_TOOL_ROUNDS  # hits the cap exactly, never exceeds it
    assert events[-1] == ("done", None)


# --- read_subsystem_source (Phase 4, 2026-08-06) -- direct resolver tests --------------------------


def test_read_subsystem_source_returns_the_real_build_source_for_a_registered_subsystem():
    # Reaches the REAL catalog registry + inspect.getsource -- not a stub -- for lofted_spindle, the
    # exact motivating example named in this phase's plan (a bellmouth intake wants to see its loft
    # technique, not bracket.py's plain extrude-and-cut).
    import inspect

    from packages.agents.read_subsystem_provider import read_subsystem_source
    from packages.subsystems import get_subsystem_model

    text = read_subsystem_source("lofted_spindle")
    assert text == inspect.getsource(get_subsystem_model("lofted_spindle").build)
    assert "loft" in text.lower()


def test_read_subsystem_source_unknown_name_returns_a_clean_message_and_never_raises():
    from packages.agents.read_subsystem_provider import read_subsystem_source

    text = read_subsystem_source("totally_not_a_real_subsystem")
    assert isinstance(text, str)
    assert "No subsystem named" in text
    assert "totally_not_a_real_subsystem" in text


def test_read_subsystem_source_truncates_a_genuinely_oversized_build_source(monkeypatch):
    # Mirrors test_sandbox_stdout_and_stderr_are_truncated_to_a_sane_length in
    # test_generated_subsystem_store.py -- every OTHER read_subsystem_source test exercises a real
    # catalog subsystem's build() source, which is always well under _MAX_SOURCE_CHARS, so none of
    # them can ever reach the truncation branch. Monkeypatch inspect.getsource (not the source of a
    # real subsystem, which we don't control the length of) to return a genuinely-oversized string, so
    # an off-by-one, a wrong slice/append order, or a broken marker would actually fail this test.
    import packages.agents.read_subsystem_provider as read_subsystem_provider_module
    from packages.agents.read_subsystem_provider import _MAX_SOURCE_CHARS, read_subsystem_source

    huge_source = "x" * (_MAX_SOURCE_CHARS * 3)
    monkeypatch.setattr(read_subsystem_provider_module.inspect, "getsource", lambda fn: huge_source)

    text = read_subsystem_source("lofted_spindle")

    marker = "\n... (truncated)"
    assert len(text) == _MAX_SOURCE_CHARS + len(marker)
    assert text == huge_source[:_MAX_SOURCE_CHARS] + marker
    assert text.endswith(marker)


def test_read_subsystem_source_enabled_defaults_to_true(monkeypatch):
    from packages.agents.read_subsystem_provider import read_subsystem_source_enabled

    monkeypatch.delenv("ENABLE_SUBSYSTEM_SOURCE_READ", raising=False)
    assert read_subsystem_source_enabled() is True


def test_read_subsystem_source_enabled_false_when_explicitly_disabled(monkeypatch):
    from packages.agents.read_subsystem_provider import read_subsystem_source_enabled

    for off_value in ("0", "false", "False", "no", "off"):
        monkeypatch.setenv("ENABLE_SUBSYSTEM_SOURCE_READ", off_value)
        assert read_subsystem_source_enabled() is False, f"expected False for {off_value!r}"


# --- read_subsystem_source wired into stream_chat's tool loop (Phase 4, 2026-08-06) -----------------


def test_stream_chat_calls_read_subsystem_source_alone_then_continues_with_the_real_source():
    # Mirrors test_stream_chat_calls_research_tool_alone_then_continues_with_the_result exactly, but
    # for the NEW read_subsystem_source continuation tool -- called ALONE (no propose_parameter_delta
    # yet), it must trigger a continuation round with the real source text fed back, then let the
    # model finalize with a proposal on its second completion.
    import inspect

    from packages.subsystems import get_subsystem_model

    real_source = inspect.getsource(get_subsystem_model("lofted_spindle").build)
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "read_subsystem_source",
                    "arguments": '{"subsystem_name":"lofted_spindle"}'}}]},
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"content": "Building it now."}}]}
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "make a bellmouth intake"}], ledger_json="{}"))

    assert len(calls) == 2  # the continuation round actually happened
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]
    # read_subsystem_source has no display-worthy event of its own (unlike research_reference's
    # ('research', finding)) -- its result only ever needs to reach the model, not the UI.
    assert not any(k == "research" for k, _ in events)

    round2_messages = calls[1]["messages"]
    assistant_msg = next(m for m in round2_messages if m.get("role") == "assistant" and m.get("tool_calls"))
    assert assistant_msg["tool_calls"][0] == {
        "id": "call_1", "type": "function",
        "function": {"name": "read_subsystem_source", "arguments": '{"subsystem_name":"lofted_spindle"}'},
    }
    tool_msg = next(m for m in round2_messages if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "call_1"
    fed_back = json.loads(tool_msg["content"])
    assert fed_back["source"] == real_source


def test_stream_chat_read_subsystem_source_unknown_name_returns_clean_not_found_and_still_continues():
    # An unregistered subsystem name must never crash or infinite-loop the round loop -- just a
    # clean "not found" tool result fed back, same never-fabricate discipline
    # test_stream_chat_research_returning_none_still_continues_without_a_research_event already
    # covers for research_reference's own "no results" branch.
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "read_subsystem_source",
                    "arguments": '{"subsystem_name":"totally_not_a_real_subsystem"}'}}]},
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "read something bogus"}], ledger_json="{}"))

    assert len(calls) == 2  # exactly one continuation round -- bounded, not an infinite loop
    tool_msg = next(m for m in calls[1]["messages"] if m.get("role") == "tool")
    fed_back = json.loads(tool_msg["content"])
    assert "No subsystem named" in fed_back["source"]
    assert not any(k == "error" for k, _ in events)  # a clean tool result, not a crash
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]
    assert events[-1] == ("done", None)


def test_stream_chat_read_subsystem_source_malformed_json_returns_clean_message_and_still_continues():
    # R2-confirmed gap (low, 2026-08-06 follow-up): every other read_subsystem_source-through-
    # stream_chat test above supplies syntactically VALID JSON arguments (a real subsystem name or an
    # unregistered-but-well-formed one) -- none exercises _execute_read_subsystem_source's own
    # malformed-tool-call-JSON branch (the "could not be parsed" string, openrouter_provider.py:580)
    # through the actual dispatch loop, unlike propose_parameter_delta's malformed-arguments handling,
    # already covered by test_stream_chat_malformed_tool_call_json_yields_error_not_silent_continue.
    # Unlike that propose_parameter_delta case, a continuation tool's raw `arguments` string is NEVER
    # json.loads'd by the round loop itself (see _stream_round's own docstring -- it only concatenates
    # fragments) -- it reaches the handler, and therefore _execute_read_subsystem_source's own
    # try/except, completely unvalidated. A regression that made that branch raise instead of
    # returning a string, or return the wrong message, would either crash this whole stream_chat call
    # or hand the model a confusing generic error instead of degrading to a clean tool-result message.
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "read_subsystem_source",
                    "arguments": '{"subsystem_name": }'}}]},  # syntactically invalid JSON
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "read something malformed"}], ledger_json="{}"))

    assert len(calls) == 2  # exactly one continuation round -- the malformed call never crashed or looped
    tool_msg = next(m for m in calls[1]["messages"] if m.get("role") == "tool")
    fed_back = json.loads(tool_msg["content"])
    assert fed_back["source"] == "The subsystem name argument for this tool call could not be parsed."
    assert not any(k == "error" for k, _ in events)  # a clean tool result, not a crash
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]
    assert events[-1] == ("done", None)


def test_stream_chat_multiple_continuation_tools_in_the_same_round_share_one_continuation(monkeypatch):
    # The generalization this phase adds (2026-08-06): when the model calls TWO DIFFERENT
    # continuation-shaped tools ALONE in the same round (no propose_parameter_delta yet), both
    # results are fed back in ONE shared continuation round -- not a hardcoded single-tool branch,
    # and not one continuation round per tool either.
    from packages.agents.research_provider import ResearchFinding
    finding = ResearchFinding(query="q", summary="s")
    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: True)
    monkeypatch.setattr("packages.agents.openrouter_provider.get_research_provider",
                         lambda: _fake_research_provider(finding))

    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "research_reference", "arguments": '{"query":"q"}'}},
                {"index": 1, "id": "call_2", "function": {
                    "name": "read_subsystem_source",
                    "arguments": '{"subsystem_name":"lofted_spindle"}'}},
            ]}, "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_3", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(messages=[{"role": "user", "content": "x"}], ledger_json="{}"))

    assert len(calls) == 2  # ONE shared continuation round, not two
    assert [p for k, p in events if k == "research"] == [finding]
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]

    round2_messages = calls[1]["messages"]
    assistant_msg = next(m for m in round2_messages if m.get("role") == "assistant" and m.get("tool_calls"))
    assert len(assistant_msg["tool_calls"]) == 2
    tool_msgs = [m for m in round2_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert {m["tool_call_id"] for m in tool_msgs} == {"call_1", "call_2"}


def test_stream_chat_continuation_handler_raising_yields_error_then_done_not_uncaught(monkeypatch):
    # R3-confirmed defect (low, Phase 4 follow-up, 2026-08-06): the generic continuation-handler
    # dispatch loop must never let a handler's own bug escape this generator uncaught. Every handler
    # currently here promises "never raises" in its own docstring, but that promise living only on
    # each handler individually -- with no backstop in the shared loop -- meant a future handler (e.g.
    # propose_custom_geometry's sandboxed build) breaking that promise would bypass the explicit
    # ('error', ...) + ('done', None) contract stream_chat's own docstring guarantees, degrading to
    # app.py's much coarser route-level backstop instead of a specific, actionable message.
    def _boom(self, arguments):
        raise RuntimeError("sandboxed build blew up")

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider."
        "_handle_read_subsystem_source_tool_call",
        _boom)

    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {
                "name": "read_subsystem_source",
                "arguments": '{"subsystem_name":"lofted_spindle"}'}}]},
            "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "read something"}], ledger_json="{}"))

    assert len(calls) == 1  # never reached a second completion request -- failed on the first round
    assert events[-1] == ("done", None)
    errors = [msg for k, msg in events if k == "error"]
    assert len(errors) == 1  # exactly the loop's own backstop message, no duplicate/contradictory ones
    assert "read_subsystem_source" in errors[0]
    assert "sandboxed build blew up" in errors[0]


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


def test_stream_chat_accepts_an_optional_project_id_with_no_behavior_change():
    # R3-confirmed defect (low, Phase 4 follow-up, 2026-08-06): the continuation-handler dispatch
    # contract -- (arguments: str) -> (dict, event|None) -- had no channel for call-scoped context
    # (conversation history, a project id) beyond a tool call's own `arguments` string, and
    # `project_id` was not even a `stream_chat` parameter at all. It is now optional, keyword-only,
    # and additive -- no handler offered by this phase reads it (see the "CALL-SCOPED CONTEXT" note
    # on the dispatch block in openrouter_provider.py) -- so supplying it must be a complete no-op:
    # a call with `project_id=` and an otherwise-identical call without it must yield byte-identical
    # events, proving this doesn't perturb the round loop / existing tools in any way.
    def fake_stream(*, url, headers, json):
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {
                "name": "propose_parameter_delta",
                "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
            "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    without_project_id = list(prov.stream_chat(
        messages=[{"role": "user", "content": "x"}], ledger_json="{}"))
    with_project_id = list(prov.stream_chat(
        messages=[{"role": "user", "content": "x"}], ledger_json="{}", project_id="proj-123"))

    assert without_project_id == with_project_id
    assert [p for k, p in with_project_id if k == "proposal"][0].deltas == \
        [ParameterDelta(target_node=SKIN, requested_value=3.0)]


# --- propose_custom_geometry (Phase 5 of the AI-generated-custom-geometry plan, 2026-08-06) ---------
# Wires Phase 3's already-built-and-verified registration gate
# (packages/subsystems/generated_registration.py::register_generated_subsystem) into the live
# conversational tool loop. Gated behind ENABLE_AI_GENERATED_SUBSYSTEMS, default OFF (unlike
# read_subsystem_source's default-ON — this has real write/registration consequences, see
# custom_geometry_provider.py's own module docstring).

HAS_B123D = importlib.util.find_spec("build123d") is not None


@pytest.fixture
def _clean_generated_registry():
    """Mirrors tests/subsystems/test_generated_registration.py::_clean_registry exactly — an accepted
    registration mutates the process-global SUBSYSTEM_REGISTRY/SUBSYSTEM_MODELS dicts (the same global
    state production uses) AND installs a module under sys.modules, regardless of whether
    `generated_dir` points at a real or a tmp_path directory — only WHERE the .py file is written/
    imported FROM is redirected by `generated_dir`, not whether the process-global registry itself is
    mutated. Track what existed before and remove only what a test actually added."""
    import sys

    import packages.subsystems as subsystems_pkg
    before = set(subsystems_pkg.SUBSYSTEM_REGISTRY)
    before_modules = set(sys.modules)
    yield
    for name in set(subsystems_pkg.SUBSYSTEM_REGISTRY) - before:
        subsystems_pkg.SUBSYSTEM_REGISTRY.pop(name, None)
        subsystems_pkg.SUBSYSTEM_MODELS.pop(name, None)
    for mod_name in set(sys.modules) - before_modules:
        if mod_name.startswith("packages.subsystems.generated."):
            sys.modules.pop(mod_name, None)


def test_custom_geometry_enabled_defaults_to_false(monkeypatch):
    from packages.agents.custom_geometry_provider import custom_geometry_enabled
    monkeypatch.delenv("ENABLE_AI_GENERATED_SUBSYSTEMS", raising=False)
    assert custom_geometry_enabled() is False


def test_custom_geometry_enabled_true_for_various_on_values(monkeypatch):
    from packages.agents.custom_geometry_provider import custom_geometry_enabled
    for on_value in ("1", "true", "TRUE", "yes", "On"):
        monkeypatch.setenv("ENABLE_AI_GENERATED_SUBSYSTEMS", on_value)
        assert custom_geometry_enabled() is True, f"expected True for {on_value!r}"


def test_custom_geometry_enabled_false_for_various_off_values(monkeypatch):
    from packages.agents.custom_geometry_provider import custom_geometry_enabled
    for off_value in ("0", "false", "no", "off", "garbage"):
        monkeypatch.setenv("ENABLE_AI_GENERATED_SUBSYSTEMS", off_value)
        assert custom_geometry_enabled() is False, f"expected False for {off_value!r}"


def test_stream_chat_omits_custom_geometry_tool_when_disabled(monkeypatch):
    # R3 (2026-08-07, CONFIRMED, low): the original version of this test relied on the AMBIENT
    # default (never actually unset ENABLE_AI_GENERATED_SUBSYSTEMS itself) and only ever inspected
    # the wire-level tool-name set -- it never probed `continuation_handlers`, so a future edit that
    # accidentally moved `continuation_handlers[_CUSTOM_GEOMETRY_FN_NAME] = _custom_geometry_handler`
    # outside the `if custom_geometry_enabled():` guard (registering the DISPATCH handler even though
    # the tool itself is correctly withheld from plain_tools/strict_tools) would sail through
    # unnoticed. Fixed two ways: (1) explicit `monkeypatch.delenv` instead of trusting the ambient
    # environment, and (2) a second round that has the (hypothetically hallucinating) model call
    # propose_custom_geometry ANYWAY even though it was never offered -- if the handler were
    # mistakenly registered, `tc["name"] in continuation_handlers` would be True, triggering a real
    # continuation round AND a ('custom_geometry', ...) event; since it's correctly un-registered,
    # neither the round loop nor stream_chat's own caller ever sees that tool name treated as
    # continuation-shaped, proving `continuation_handlers` itself has no entry for it (not just that
    # the offered tool list omits it).
    monkeypatch.delenv("ENABLE_AI_GENERATED_SUBSYSTEMS", raising=False)
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["tools"] = json["tools"]
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    names = {t["function"]["name"] for t in captured["tools"]}
    assert "propose_custom_geometry" not in names
    assert names == {"propose_parameter_delta", "read_subsystem_source"}  # read_subsystem_source is default-on

    # Probe: the model calls propose_custom_geometry ALONE anyway, despite it never having been
    # offered. If `continuation_handlers` genuinely has no entry for it (the correct, guarded
    # behavior), this tool call matches neither the continuation dispatch nor the one hardcoded
    # terminal tool name (`propose_parameter_delta`) -- it is dropped, no second round is attempted,
    # and no ('custom_geometry', ...) event is ever yielded.
    disabled_probe_args = json.dumps({
        "subsystem_name": "should_never_register",
        "description": "probing a disabled tool -- must never dispatch",
        "build_code": "def build(p):\n    import build123d as bd\n    return bd.Box(1, 1, 1)\n",
        "params": [],
    })
    probe_calls = []

    def fake_stream_probe(*, url, headers, json):
        probe_calls.append(json)
        yield {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "function": {
                "name": "propose_custom_geometry", "arguments": disabled_probe_args}}]},
            "finish_reason": "tool_calls"}]}

    probe_prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream_probe)
    probe_events = list(probe_prov.stream_chat(
        messages=[{"role": "user", "content": "try the disabled tool"}], ledger_json="{}"))

    assert len(probe_calls) == 1  # no continuation round -- the handler was never registered
    assert [k for k, _ in probe_events if k == "custom_geometry"] == []


def test_stream_chat_offers_all_three_continuation_tools_when_all_enabled_byte_identical_otherwise(monkeypatch):
    # Regression: research_reference/read_subsystem_source's existing tool-offering behavior must be
    # completely unchanged by propose_custom_geometry landing alongside them -- all three appear
    # together, none crowds another out.
    #
    # R3 (2026-08-07, CONFIRMED, low): the original version of this test only compared the SET of
    # tool NAMES (`names == {...}`) despite its own name promising a "byte identical" check -- it
    # would have stayed green even if propose_custom_geometry landing had mutated
    # research_reference's or read_subsystem_source's own description text or parameters schema
    # (e.g. a shared-dict mutation, or a copy-paste edit that touched the wrong tool literal). Fixed
    # by capturing the BASELINE full tool dicts (description + parameters schema, not just the name)
    # with only research_reference/read_subsystem_source enabled (custom_geometry disabled), then
    # asserting those exact two entries are byte-for-byte (`==`) unchanged in the all-three-enabled
    # capture -- not merely present by name.
    def fake_stream_capturing(store):
        def fake_stream(*, url, headers, json):
            store["tools"] = json["tools"]
            yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}
        return fake_stream

    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: True)

    baseline = {}
    monkeypatch.setattr("packages.agents.openrouter_provider.custom_geometry_enabled", lambda: False)
    baseline_prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream_capturing(baseline))
    list(baseline_prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))
    baseline_by_name = {t["function"]["name"]: t for t in baseline["tools"]}
    assert set(baseline_by_name) == {"propose_parameter_delta", "research_reference", "read_subsystem_source"}

    captured = {}
    monkeypatch.setattr("packages.agents.openrouter_provider.custom_geometry_enabled", lambda: True)

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream_capturing(captured))
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    names = {t["function"]["name"] for t in captured["tools"]}
    assert names == {"propose_parameter_delta", "research_reference", "read_subsystem_source",
                      "propose_custom_geometry"}

    # The actual "byte identical" claim: full tool dict (description + parameters schema), not just
    # the name, is unchanged for the two pre-existing continuation tools.
    captured_by_name = {t["function"]["name"]: t for t in captured["tools"]}
    assert captured_by_name["research_reference"] == baseline_by_name["research_reference"]
    assert captured_by_name["read_subsystem_source"] == baseline_by_name["read_subsystem_source"]


def test_stream_chat_calls_custom_geometry_tool_alone_accepted_then_places_an_instance(monkeypatch):
    # TWO-ROUND flow: round 1 the model calls propose_custom_geometry ALONE (no
    # propose_parameter_delta yet) with a valid candidate's arguments -- it must trigger a
    # continuation round, the tool-result content fed back must reflect accepted=True, and a
    # ('custom_geometry', RegistrationResult) event must be yielded with accepted=True. Round 2 the
    # model reacts by placing an instance of the newly-registered type via an ordinary
    # propose_parameter_delta add_instance op (already-working, unmodified machinery -- Phase 5's own
    # scope is registration only) -- the full two-round flow must complete and yield that proposal.
    #
    # `_execute_custom_geometry` itself is mocked here so this test is isolated to the ROUND-LOOP
    # dispatch mechanics (continuation happening, correct tool-result/event shape) -- mirrors how
    # test_stream_chat_calls_research_tool_alone_then_continues_with_the_result mocks
    # get_research_provider() rather than hitting a real network call. Phase 3's own registration-gate
    # CORRECTNESS (the four floors, sandboxed build, restart-survival) is already exhaustively covered
    # by tests/subsystems/test_generated_registration.py -- re-proving it here would be redundant, not
    # additional coverage.
    from packages.ledger.deltas import InstanceOp
    from packages.subsystems.generated_registration import RegistrationResult

    monkeypatch.setattr("packages.agents.openrouter_provider.custom_geometry_enabled", lambda: True)
    fake_result = RegistrationResult(
        accepted=True, outcome="registered", subsystem_name="finned_heat_spreader",
        attempt_id="att_fake0001", model="deepseek/deepseek-chat", sha256="ab" * 32,
        sandbox_status="OK", volume_mm3=1234.5,
        bbox_mm=((0.0, 0.0, 0.0), (40.0, 30.0, 5.0)),
    )
    captured_kwargs = {}

    def fake_execute(self, arguments, *, project_id, user_request_excerpt, store=None, generated_dir=None):
        captured_kwargs["project_id"] = project_id
        captured_kwargs["user_request_excerpt"] = user_request_excerpt
        captured_kwargs["arguments"] = arguments
        return fake_result

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider._execute_custom_geometry",
        fake_execute,
    )

    candidate_args = json.dumps({
        "subsystem_name": "finned_heat_spreader",
        "description": "A finned heat spreader plate.",
        "build_code": ("def build(p):\n    import build123d as bd\n"
                        "    return bd.Box(p.length_mm, p.width_mm, p.height_mm)\n"),
        "params": [{"name": "length_mm", "default": 40.0, "min": 5.0, "max": 200.0, "unit": "mm"}],
    })
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "propose_custom_geometry", "arguments": candidate_args}}]},
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"content": "Registered it. Adding to the design now."}}]}
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": ('{"instance_ops":[{"op":"add_instance",'
                                   '"subsystem_type":"finned_heat_spreader"}]}')}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", model="deepseek/deepseek-chat", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "make a custom finned heat spreader"}],
        ledger_json="{}", project_id="proj_abc"))

    assert len(calls) == 2  # the continuation round actually happened

    cg_events = [p for k, p in events if k == "custom_geometry"]
    assert len(cg_events) == 1 and cg_events[0] is fake_result
    assert cg_events[0].accepted is True

    round2_messages = calls[1]["messages"]
    assistant_msg = next(m for m in round2_messages if m.get("role") == "assistant" and m.get("tool_calls"))
    assert assistant_msg["tool_calls"][0] == {
        "id": "call_1", "type": "function",
        "function": {"name": "propose_custom_geometry", "arguments": candidate_args},
    }
    tool_msg = next(m for m in round2_messages if m.get("role") == "tool")
    fed_back = json.loads(tool_msg["content"])
    assert fed_back == {
        "accepted": True, "outcome": "registered", "subsystem_name": "finned_heat_spreader",
        "rejected_floor": None, "rejection_reason": None,
    }

    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].instance_ops == [
        InstanceOp(op="add_instance", subsystem_type="finned_heat_spreader")]
    assert events[-1] == ("done", None)

    # project_id (from stream_chat's own real parameter) and the user's own most recent message text
    # both reached _execute_custom_geometry -- the closure built inside stream_chat's own
    # custom_geometry_enabled() block actually captured them, not just silently dropped them.
    assert captured_kwargs["project_id"] == "proj_abc"
    assert captured_kwargs["user_request_excerpt"] == "make a custom finned heat spreader"


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_stream_chat_real_gate_accepted_end_to_end_then_places_an_instance(
        monkeypatch, tmp_path, _clean_generated_registry):
    # R3 (2026-08-07, CONFIRMED, medium): closes the one gap none of the three existing tests covers.
    # test_stream_chat_calls_custom_geometry_tool_alone_accepted_then_places_an_instance (just above)
    # proves the ROUND-LOOP dispatch mechanics, but mocks _execute_custom_geometry entirely -- no
    # LLM-shaped tool call ever reaches the real registration gate there.
    # test_stream_chat_custom_geometry_disallowed_code_yields_clean_rejection_not_a_crash runs the real
    # gate through the full round loop, but only for a REJECTED outcome (safe, because a floor-3
    # rejection has zero filesystem/registry side effects).
    # test_execute_custom_geometry_accepted_corpus_row_carries_the_real_model_string runs the real gate
    # for an ACCEPTED outcome, but calls _execute_custom_geometry directly -- bypassing stream_chat's
    # round loop and the placement round entirely.
    #
    # This test is the missing middle: a real, LLM-shaped propose_custom_geometry tool call flows
    # through stream_chat's ACTUAL continuation dispatch (nothing on the custom-geometry path is
    # mocked) into a genuinely ACCEPTED register_generated_subsystem() run -- a real out-of-process
    # sandboxed build, a real module written to disk, imported, and live in SUBSYSTEM_REGISTRY --
    # followed by a real second round in which the model places an instance of the newly-registered
    # type via an ordinary propose_parameter_delta add_instance op. End to end.
    #
    # Two things are monkeypatched, both pure test-isolation (never touching what the production code
    # actually does, so this never weakens what's being proved): the module-global default
    # generated_dir constant that register_generated_subsystem falls back to when no override is
    # passed (stream_chat's own closure deliberately never threads a generated_dir kwarg through --
    # see _execute_custom_geometry's own docstring -- so redirecting the DEFAULT is the only way to
    # keep this test from writing into the real packages/subsystems/generated/ directory, mirroring
    # what test_execute_custom_geometry_accepted_corpus_row_carries_the_real_model_string does via an
    # explicit generated_dir= kwarg on a direct call); and generation_attempt_store_from_env, so the
    # corpus row lands in an injected, inspectable InMemoryGenerationAttemptStore instead of a real DB
    # connection attempt.
    import packages.subsystems.generated_registration as generated_registration
    from packages.ledger.deltas import InstanceOp
    from packages.subsystems import get_subsystem_model
    from packages.truth_plane.generated_subsystem_store import InMemoryGenerationAttemptStore

    monkeypatch.setattr(generated_registration, "_DEFAULT_GENERATED_DIR", tmp_path)
    store = InMemoryGenerationAttemptStore()
    monkeypatch.setattr(
        "packages.truth_plane.generated_subsystem_store.generation_attempt_store_from_env",
        lambda: store,
    )
    monkeypatch.setattr("packages.agents.openrouter_provider.custom_geometry_enabled", lambda: True)

    subsystem_name = "gen_test_openrouter_phase5_full_pipeline_2026"
    candidate_args = json.dumps({
        "subsystem_name": subsystem_name,
        "description": "Phase 5 full-pipeline test fixture -- a plain box, never a real catalog part.",
        "build_code": ("def build(p):\n    import build123d as bd\n"
                        "    return bd.Box(p.width_mm, p.depth_mm, p.height_mm)\n"),
        "params": [
            {"name": "width_mm", "default": 10.0, "min": 1.0, "max": 100.0, "unit": "mm"},
            {"name": "depth_mm", "default": 8.0, "min": 1.0, "max": 100.0, "unit": "mm"},
            {"name": "height_mm", "default": 6.0, "min": 1.0, "max": 100.0, "unit": "mm"},
        ],
    })
    # built OUTSIDE fake_stream, since fake_stream's own `json` PARAMETER shadows the `json` MODULE
    # within its body (same reason every other fake_stream in this file pre-builds its arguments
    # string, e.g. `delta_args`, rather than calling json.dumps(...) from inside the function).
    placement_args = json.dumps({"instance_ops": [
        {"op": "add_instance", "subsystem_type": subsystem_name}]})
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "propose_custom_geometry", "arguments": candidate_args}}]},
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"content": "Registered it. Adding to the design now."}}]}
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta", "arguments": placement_args}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(
        api_key="x", model="test-vendor/full-pipeline-model", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "make me a real test box end to end"}],
        ledger_json="{}", project_id="proj_full_pipeline"))

    assert len(calls) == 2  # the continuation round actually happened through the REAL gate

    cg_events = [p for k, p in events if k == "custom_geometry"]
    assert len(cg_events) == 1
    result = cg_events[0]
    assert result.accepted is True
    assert result.outcome == "registered"
    assert result.subsystem_name == subsystem_name
    assert result.model == "test-vendor/full-pipeline-model"  # the REAL self.model, reached via stream_chat

    tool_msg = next(m for m in calls[1]["messages"] if m.get("role") == "tool")
    fed_back = json.loads(tool_msg["content"])
    assert fed_back == {
        "accepted": True, "outcome": "registered", "subsystem_name": subsystem_name,
        "rejected_floor": None, "rejection_reason": None,
    }

    # the corpus row genuinely landed in the injected store, carrying the real project_id/model/
    # user_request_excerpt -- reached via stream_chat's own closure, not a hand-built call.
    row = store.get(result.attempt_id)
    assert row is not None
    assert row.project_id == "proj_full_pipeline"
    assert row.model == "test-vendor/full-pipeline-model"
    assert row.user_request_excerpt == "make me a real test box end to end"

    # the new type is genuinely resolvable in-process the instant registration returned -- same
    # acceptance criterion the other real-gate tests use.
    assert get_subsystem_model(subsystem_name) is not None

    # round 2: the model reacts by placing an instance of the newly-registered type via ordinary,
    # already-working propose_parameter_delta machinery -- proves the FULL two-round flow (real gate
    # -> placement) completes end to end, not just the registration half.
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].instance_ops == [
        InstanceOp(op="add_instance", subsystem_type=subsystem_name)]
    assert events[-1] == ("done", None)


def test_stream_chat_custom_geometry_disallowed_code_yields_clean_rejection_not_a_crash(monkeypatch):
    # A bad/malicious build_code (here: a disallowed 'import os') must reject cleanly through the REAL
    # registration gate -- a ('custom_geometry', RegistrationResult(accepted=False, ...)) event, NOT a
    # crash, NOT an ('error', ...) event -- and the round loop must still complete normally. Goes
    # through the REAL gate (no mocking) because a floor-3 (AST denylist) rejection is guaranteed to
    # have ZERO filesystem/registry side effects -- it's rejected before ever reaching the sandboxed
    # build or the write+import step (see generated_registration.py's own floor ordering) -- so this is
    # safe to run against the real, unmocked register_generated_subsystem without a generated_dir
    # override, unlike an ACCEPTED candidate would be.
    from packages.subsystems.generated_registration import FLOOR_DISALLOWED_CODE

    monkeypatch.setattr("packages.agents.openrouter_provider.custom_geometry_enabled", lambda: True)
    bad_args = json.dumps({
        "subsystem_name": "gen_test_disallowed_import_stream_chat_2026",
        "description": "malicious test fixture -- must never register",
        "build_code": "import os\ndef build(p):\n    return None\n",
        "params": [],
    })
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "propose_custom_geometry", "arguments": bad_args}}]},
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "write me something sneaky"}], ledger_json="{}"))

    assert len(calls) == 2  # exactly one continuation round -- rejection is not a crash or infinite loop
    cg_events = [p for k, p in events if k == "custom_geometry"]
    assert len(cg_events) == 1
    result = cg_events[0]
    assert result.accepted is False
    assert result.outcome == "rejected"
    assert result.rejected_floor == FLOOR_DISALLOWED_CODE
    assert "os" in (result.rejection_reason or "")

    tool_msg = next(m for m in calls[1]["messages"] if m.get("role") == "tool")
    fed_back = json.loads(tool_msg["content"])
    assert fed_back["accepted"] is False
    assert fed_back["rejected_floor"] == FLOOR_DISALLOWED_CODE

    assert not any(k == "error" for k, _ in events)  # a clean rejection, not a crash
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]
    assert events[-1] == ("done", None)


def test_stream_chat_custom_geometry_malformed_json_returns_clean_rejection_and_still_continues(monkeypatch):
    # Mirrors test_stream_chat_read_subsystem_source_malformed_json_returns_clean_message_and_still_continues
    # -- a continuation tool's raw `arguments` string is never json.loads'd by the round loop itself
    # (see _stream_round's own docstring), so genuinely malformed JSON reaches
    # _execute_custom_geometry's own try/except completely unvalidated. Must degrade to a clean
    # rejection, never a crash.
    monkeypatch.setattr("packages.agents.openrouter_provider.custom_geometry_enabled", lambda: True)
    calls = []

    def fake_stream(*, url, headers, json):
        calls.append(json)
        if len(calls) == 1:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {
                    "name": "propose_custom_geometry",
                    "arguments": '{"subsystem_name": }'}}]},  # syntactically invalid JSON
                "finish_reason": "tool_calls"}]}
        else:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_2", "function": {
                    "name": "propose_parameter_delta",
                    "arguments": '{"deltas":[{"target_node":"' + SKIN + '","requested_value":3.0}]}'}}]},
                "finish_reason": "tool_calls"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    events = list(prov.stream_chat(
        messages=[{"role": "user", "content": "propose something malformed"}], ledger_json="{}"))

    assert len(calls) == 2  # the malformed call never crashed or looped
    cg_events = [p for k, p in events if k == "custom_geometry"]
    assert len(cg_events) == 1
    assert cg_events[0].accepted is False
    assert cg_events[0].rejected_floor == "malformed_tool_call"
    assert not any(k == "error" for k, _ in events)  # a clean tool result, not a crash
    proposals = [p for k, p in events if k == "proposal"]
    assert proposals and proposals[0].deltas == [ParameterDelta(target_node=SKIN, requested_value=3.0)]
    assert events[-1] == ("done", None)


def test_execute_custom_geometry_rejects_a_tool_call_that_tries_to_set_caller_supplied_fields():
    # Security property from custom_geometry_provider.py's own module docstring: "a hostile/careless
    # model putting a model/project_id field in its own tool-call JSON must never be trusted for
    # these" -- GeneratedSubsystemCandidateArgs has extra="forbid", so a tool call that tries to smuggle
    # a caller-supplied `project_id` (or `model`) field alongside the legitimate LLM-controlled fields
    # must fail to parse, never silently pass that value through into the real candidate.
    prov = OpenRouterDeltaProvider(api_key="x", model="real-vendor/real-model")
    hostile_args = json.dumps({
        "subsystem_name": "hostile_test_part", "description": "d",
        "build_code": "def build(p):\n    return None\n", "params": [],
        "project_id": "attacker-controlled-project-id",
    })

    result = prov._execute_custom_geometry(
        hostile_args, project_id="the_real_project_id", user_request_excerpt="x")

    assert result.accepted is False
    assert result.rejected_floor == "malformed_tool_call"


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_execute_custom_geometry_accepted_corpus_row_carries_the_real_model_string(
        tmp_path, _clean_generated_registry):
    # "A test confirming the corpus row (via a real InMemoryGenerationAttemptStore injected) carries
    # the REAL self.model string, not a placeholder" -- goes through the REAL registration gate (an
    # actual out-of-process sandboxed build), with an injected store + tmp_path generated_dir so this
    # never touches the real packages/subsystems/generated/ directory (mirrors
    # test_generated_registration.py's own established discipline).
    from packages.truth_plane.generated_subsystem_store import InMemoryGenerationAttemptStore

    store = InMemoryGenerationAttemptStore()
    real_model_string = "test-vendor/test-model-v9-not-a-placeholder"
    prov = OpenRouterDeltaProvider(api_key="x", model=real_model_string)
    good_args = json.dumps({
        "subsystem_name": "gen_test_openrouter_phase5_box_2026",
        "description": "Phase 5 test fixture -- a plain box, never a real catalog part.",
        "build_code": ("def build(p):\n    import build123d as bd\n"
                        "    return bd.Box(p.width_mm, p.depth_mm, p.height_mm)\n"),
        "params": [
            {"name": "width_mm", "default": 10.0, "min": 1.0, "max": 100.0, "unit": "mm"},
            {"name": "depth_mm", "default": 8.0, "min": 1.0, "max": 100.0, "unit": "mm"},
            {"name": "height_mm", "default": 6.0, "min": 1.0, "max": 100.0, "unit": "mm"},
        ],
    })

    result = prov._execute_custom_geometry(
        good_args, project_id="proj_phase5_test", user_request_excerpt="make me a test box",
        store=store, generated_dir=tmp_path,
    )

    assert result.accepted is True
    assert result.outcome == "registered"
    assert result.model == real_model_string  # RegistrationResult's own additive field
    assert result.sha256  # populated too, additive alongside model

    row = store.get(result.attempt_id)
    assert row is not None
    assert row.model == real_model_string  # the REAL self.model, not a placeholder like "unknown"
    assert row.subsystem_name == "gen_test_openrouter_phase5_box_2026"
    assert row.project_id == "proj_phase5_test"
    assert row.user_request_excerpt == "make me a test box"

    from packages.subsystems import get_subsystem_model
    assert get_subsystem_model("gen_test_openrouter_phase5_box_2026") is not None


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_execute_custom_geometry_never_raises_when_corpus_store_put_fails_after_acceptance(
        tmp_path, _clean_generated_registry):
    # Phase 5 write-path repair (2026-08-06, reviewer R2 CONFIRMED, medium) regression -- exact repro
    # from the finding: a candidate that passes all four floors (real out-of-process sandboxed build,
    # module written+imported+live in SUBSYSTEM_REGISTRY) whose injected store's put() raises must still
    # come back as a normal, accepted RegistrationResult from `_execute_custom_geometry` itself -- not a
    # raw exception. Before the fix (in generated_registration.py's own `_finish()`, guarding
    # `resolved_store.put()`), calling `prov._execute_custom_geometry(...)` here with this broken store
    # raised straight out, which is exactly what would have been caught only by stream_chat's generic
    # per-round backstop several layers up -- an ('error', ...) event with no ('custom_geometry',
    # RegistrationResult) ever yielded, so app.py's /chat route would never learn the outcome.
    class _StorePutAlwaysRaises:
        def put(self, attempt):
            raise RuntimeError("simulated DB outage on put()")

        def get(self, attempt_id):
            return None

        def list(self, *, project_id=None, limit=100):
            return []

    prov = OpenRouterDeltaProvider(api_key="x", model="test-vendor/test-model")
    good_args = json.dumps({
        "subsystem_name": "gen_test_openrouter_phase5_store_outage_2026",
        "description": "Phase 5 regression fixture -- a plain box, never a real catalog part.",
        "build_code": ("def build(p):\n    import build123d as bd\n"
                        "    return bd.Box(p.width_mm, p.depth_mm, p.height_mm)\n"),
        "params": [
            {"name": "width_mm", "default": 10.0, "min": 1.0, "max": 100.0, "unit": "mm"},
            {"name": "depth_mm", "default": 8.0, "min": 1.0, "max": 100.0, "unit": "mm"},
            {"name": "height_mm", "default": 6.0, "min": 1.0, "max": 100.0, "unit": "mm"},
        ],
    })

    # This call must not raise -- the whole point of the fix.
    result = prov._execute_custom_geometry(
        good_args, project_id="proj_phase5_test", user_request_excerpt="make me a test box",
        store=_StorePutAlwaysRaises(), generated_dir=tmp_path,
    )

    assert result.accepted is True
    assert result.outcome == "registered"
    assert result.subsystem_name == "gen_test_openrouter_phase5_store_outage_2026"

    from packages.subsystems import get_subsystem_model
    # the registry mutation genuinely happened despite the store outage -- confirms this isn't a case
    # where the fix papered over a real registration failure, only recovered from a capture failure.
    assert get_subsystem_model("gen_test_openrouter_phase5_store_outage_2026") is not None


# --- model_supports_vision (vision-in-the-loop, 2026-08-05) ----------------------------------------
# Fixture is a TRIMMED but real subset of OpenRouter's actual `GET /models` response shape (fetched
# for real on 2026-08-05 against https://openrouter.ai/api/v1/models to confirm this shape before
# writing it: a top-level {"data": [...], ...} envelope, each entry keyed by "id" with an
# "architecture": {"input_modalities": [...]} block) -- not a guessed/invented shape. The two model
# ids mirror the live registry at fetch time: openai/gpt-5.6-luna is vision-capable
# (["file", "image", "text"]), deepseek/deepseek-v4-flash is text-only (["text"]).


def _fake_registry_response():
    return {
        "data": [
            {
                "id": "openai/gpt-5.6-luna",
                "canonical_slug": "openai/gpt-5.6-luna-20260709",
                "name": "OpenAI: GPT-5.6 Luna",
                "context_length": 1050000,
                "architecture": {
                    "modality": "text+image+file->text",
                    "input_modalities": ["file", "image", "text"],
                    "output_modalities": ["text"],
                    "tokenizer": "GPT",
                },
            },
            {
                "id": "deepseek/deepseek-v4-flash",
                "canonical_slug": "deepseek/deepseek-v4-flash-20260423",
                "name": "DeepSeek: DeepSeek V4 Flash 0423",
                "context_length": 1048576,
                "architecture": {
                    "modality": "text->text",
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                    "tokenizer": "DeepSeek",
                },
            },
        ],
        "total_count": 2,
        "links": {},
    }


def _reset_model_registry_cache(monkeypatch):
    # every test below gets a clean cache, regardless of what an earlier test (or an earlier import)
    # may have left in the module-level (models, fetched_at) tuple -- monkeypatch reverts this back
    # to whatever it was (None, its true initial value) once the test ends.
    monkeypatch.setattr(openrouter_provider, "_model_registry_cache", None)


def test_model_supports_vision_true_for_a_vision_capable_model(monkeypatch):
    _reset_model_registry_cache(monkeypatch)
    fake_get = lambda *, url: _fake_registry_response()
    assert model_supports_vision("openai/gpt-5.6-luna", get=fake_get) is True


def test_model_supports_vision_false_for_a_text_only_model(monkeypatch):
    _reset_model_registry_cache(monkeypatch)
    fake_get = lambda *, url: _fake_registry_response()
    assert model_supports_vision("deepseek/deepseek-v4-flash", get=fake_get) is False


def test_model_supports_vision_false_for_an_unknown_model_id():
    # not in the registry at all -- False, not an error, not a guess.
    fake_get = lambda *, url: _fake_registry_response()
    assert model_supports_vision("some-vendor/does-not-exist", get=fake_get) is False


def test_model_supports_vision_false_for_an_absent_model_id():
    # empty/None model id must short-circuit before ever calling `get` -- nothing to look up.
    fake_get = lambda *, url: (_ for _ in ()).throw(
        AssertionError("should not fetch the registry for an empty model id"))
    assert model_supports_vision("", get=fake_get) is False


def test_model_supports_vision_false_on_a_network_failure(monkeypatch):
    _reset_model_registry_cache(monkeypatch)

    def fake_get(*, url):
        raise ConnectionError("network is down")

    # never raises -- a transport failure degrades to "no, can't confirm it", exactly like
    # vision_model_configured()/validate_visual()'s own defensive posture elsewhere in this codebase.
    assert model_supports_vision("openai/gpt-5.6-luna", get=fake_get) is False


def test_model_supports_vision_false_on_a_malformed_response(monkeypatch):
    _reset_model_registry_cache(monkeypatch)
    fake_get = lambda *, url: {"unexpected": "shape", "no": "data key"}
    assert model_supports_vision("openai/gpt-5.6-luna", get=fake_get) is False


def test_model_supports_vision_caches_the_registry_within_the_ttl_window(monkeypatch):
    _reset_model_registry_cache(monkeypatch)
    calls = {"n": 0}

    def fake_get(*, url):
        calls["n"] += 1
        return _fake_registry_response()

    assert model_supports_vision("openai/gpt-5.6-luna", get=fake_get) is True
    assert model_supports_vision("deepseek/deepseek-v4-flash", get=fake_get) is False
    assert model_supports_vision("some-vendor/does-not-exist", get=fake_get) is False
    assert calls["n"] == 1  # the 2nd and 3rd calls were served from the module-level cache


def test_model_supports_vision_a_failed_fetch_does_not_poison_the_cache(monkeypatch):
    # a transient failure must not get cached as if it were a successful (empty) fetch -- the very
    # next call should get a fresh chance, not be stuck returning False for the rest of the TTL.
    _reset_model_registry_cache(monkeypatch)
    calls = {"n": 0}

    def flaky_get(*, url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("network is down")
        return _fake_registry_response()

    assert model_supports_vision("openai/gpt-5.6-luna", get=flaky_get) is False  # 1st call: fails
    assert model_supports_vision("openai/gpt-5.6-luna", get=flaky_get) is True   # 2nd call: succeeds
    assert calls["n"] == 2  # both calls actually hit `get` -- the failure wasn't cached
