"""OpenRouterDeltaProvider: function-calling wiring + parsing, via an injected fake POST (no key/net)."""

from __future__ import annotations

import json

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
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["tools"] = json["tools"]
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    assert [t["function"]["name"] for t in captured["tools"]] == ["propose_parameter_delta"]


def test_stream_chat_offers_research_tool_when_configured(monkeypatch):
    monkeypatch.setattr("packages.agents.openrouter_provider.research_provider_configured", lambda: True)
    captured = {}

    def fake_stream(*, url, headers, json):
        captured["tools"] = json["tools"]
        yield {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}

    prov = OpenRouterDeltaProvider(api_key="x", stream_post=fake_stream)
    list(prov.stream_chat(messages=[{"role": "user", "content": "hi"}], ledger_json="{}"))

    names = {t["function"]["name"] for t in captured["tools"]}
    assert names == {"propose_parameter_delta", "research_reference"}


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


def test_stream_chat_caps_at_one_continuation_round(monkeypatch):
    # If round 2 ALSO comes back as research-only (no propose_parameter_delta), a round 3 must
    # never happen -- _MAX_RESEARCH_ROUNDS is a hard cap, not a "keep going until satisfied" loop.
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

    assert len(calls) == 2  # exactly one continuation, never a third round
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
