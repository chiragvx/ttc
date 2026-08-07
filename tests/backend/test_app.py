"""FastAPI app: REST + the two-plane WebSocket (cascade + NACK paths)."""

from __future__ import annotations

import importlib.util
import time

import pytest
from fastapi.testclient import TestClient

import packages.transport.app as app_module
from packages.ledger.derived_resolver import Verdict, signature_from_params
from packages.ledger.fingerprint import fingerprint
from packages.transport.app import create_app

SKIN = "instances.root.params.skin_thickness_mm"


def _client():
    # a project starts as an empty workspace (2026-07-04) — bootstrap the bracket root every other
    # test here relies on, exactly as genesis used to seed it automatically.
    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    return c


def test_healthz_and_initial_ledger():
    c = _client()
    assert c.get("/healthz").json() == {"ok": True}
    led = c.get("/ledger").json()
    assert led['instances']['root']['params']["skin_thickness_mm"]["value"] == 2.0


def test_ws_valid_mutation_returns_cascade_and_persists():
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 3.0})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_CASCADE_UPDATE"
    m = msg["mutations_applied"][0]
    assert m["node"] == SKIN and m["value"] == 3.0 and m["status"] == "APPLIED"
    assert m["old_value"] == 2.0  # for Undo
    assert msg["telemetry_delta"]["total_mass_g"] > 0
    # committed to the shared event log
    assert c.get("/ledger").json()['instances']['root']['params']["skin_thickness_mm"]["value"] == 3.0


def test_ws_material_change_round_trips_through_the_real_mutate_path():
    """2026-07-19 fix: the copilot's actual failure mode was ParameterDelta.requested_value rejecting
    a material NAME outright at the wire — this drives the SAME real path (SessionState.mutate() via
    the WS handler, not a direct apply_delta call) end-to-end for domains.structure.material_profile."""
    c = _client()
    assert c.get("/ledger").json()["domains"]["structure"]["material_profile"] == "PLA"
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "domains.structure.material_profile", "requested_value": "ABS"})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_CASCADE_UPDATE"
    m = msg["mutations_applied"][0]
    assert m["node"] == "domains.structure.material_profile"
    assert m["value"] == "ABS" and m["old_value"] == "PLA" and m["status"] == "APPLIED"
    assert c.get("/ledger").json()["domains"]["structure"]["material_profile"] == "ABS"


def test_ws_unknown_material_name_is_nacked():
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "domains.structure.material_profile", "requested_value": "UNOBTANIUM"})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_MUTATION_REJECTED"
    assert c.get("/ledger").json()["domains"]["structure"]["material_profile"] == "PLA"


def test_ws_survives_an_unhandled_exception_in_mutate(monkeypatch):
    """foundations-audit follow-up (2026-07-22, live-reproduced): the existing malformed-frame guard
    (a few tests up) only covers the receive_json()/model_validate() step -- an exception raised
    INSIDE state.mutate() itself (cascade logic, apply_delta, telemetry -- considerably more code
    than the parse step, and so more likely to have a real bug someday) used to kill the WHOLE
    socket with no response for that mutation and left the connection unusable for every SUBSEQUENT
    mutation too: the Tier-0 interactive plane going dead until the frontend reconnects, confirmed via
    TestClient before this fix (the client's next send_json/receive_json raised outright). Now it
    must degrade to a clean REJECTED for the failing mutation while the socket stays alive for the
    next one."""
    import packages.transport.app as app_module

    orig_mutate = app_module.FileState.mutate
    calls = {"n": 0}

    def flaky_mutate(self, req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated bug deep in mutate()")
        return orig_mutate(self, req)

    monkeypatch.setattr(app_module.FileState, "mutate", flaky_mutate)

    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 3.0})
        msg = ws.receive_json()
        assert msg["event_type"] == "PARAMETER_MUTATION_REJECTED"
        assert "internal error" in msg["reason"]

        # the socket must still be alive and functional for a SUBSEQUENT mutation
        ws.send_json({"target_node": SKIN, "requested_value": 4.0})
        msg2 = ws.receive_json()
        assert msg2["event_type"] == "PARAMETER_CASCADE_UPDATE"
        assert msg2["mutations_applied"][0]["value"] == 4.0


def test_telemetry_never_touches_the_kernel_for_an_auto_laid_out_instance(monkeypatch):
    """foundations-audit follow-up (2026-07-21): `_telemetry` (the WS mutation response's
    `telemetry_delta`, and `metrics()`'s /requirements read) is the INTERACTIVE plane -- Inversion #2
    (packages/CLAUDE.md) forbids a real geometry_builder call there outright, not just "bound it with
    a timeout" the way `/mesh` legitimately does. Before this fix, `instance_world_offsets()`'s
    auto-layout spacing (`assembly.py::_y_extent_mm`) called `geometry_builder` directly for ANY
    multi-instance ledger with an auto-laid-out (unconnected) instance -- on every parameter
    mutation. This proves the doctrine property ITSELF (the builder is never invoked), not just that
    a response comes back fast/correct -- a fast, wrong answer would also pass a pure return-value
    check."""
    import dataclasses

    from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

    called: list[str] = []

    def _must_not_be_called(ledger, instance_id):
        called.append(instance_id)
        raise AssertionError("geometry_builder must never be called from the interactive plane")

    watched_bracket = dataclasses.replace(get_subsystem("bracket"), geometry_builder=_must_not_be_called)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, "bracket", watched_bracket)

    c = _client()
    # a second, auto-laid-out (no connection, no explicit transform) instance -- exactly the case
    # that used to seed/advance the auto-layout cursor via a real geometry build.
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "second"})

    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 3.0})
        msg = ws.receive_json()

    assert called == []  # the doctrine property itself
    assert msg["event_type"] == "PARAMETER_CASCADE_UPDATE"
    assert msg["telemetry_delta"]["total_mass_g"] > 0

    # /requirements (metrics()) shares the exact same _telemetry() call -- same guarantee.
    called.clear()
    assert c.get("/requirements").status_code == 200
    assert called == []


def test_ws_out_of_recommended_range_is_applied_advisory():
    """Soft bounds: WS mutation with a value past the recommended range still applies (with an
    APPLIED_ADVISORY status). The value is NOT clamped to the upper bound."""
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 9.0})
        msg = ws.receive_json()
    assert msg["mutations_applied"][0]["status"] == "APPLIED_ADVISORY"
    assert msg["mutations_applied"][0]["value"] == 9.0


def test_ws_cascade_grows_plate_depth_for_a_bigger_bolt_hole():
    """prd4.md §2.2's cascade example, live: a WS mutation that would violate bracket's
    edge-distance rule cascades plate_depth_mm up instead of being rejected, and the cascade shows
    up in cascades_applied on the SAME response as the direct mutation."""
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "instances.root.params.hole_diameter_mm", "requested_value": 15.0})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_CASCADE_UPDATE"
    assert msg["mutations_applied"][0]["value"] == 15.0
    assert len(msg["cascades_applied"]) == 1
    cascade = msg["cascades_applied"][0]
    assert cascade["node"] == "instances.root.params.plate_depth_mm"
    assert cascade["value"] == 45.0
    assert cascade["old_value"] == 40.0
    assert "edge-distance" in cascade["reason"]
    # the cascaded param is committed to the ledger too, not just reported
    led = c.get("/ledger").json()
    assert led["instances"]["root"]["params"]["plate_depth_mm"]["value"] == 45.0


def test_ws_forbidden_target_is_nacked():
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "derived.factor_of_safety", "requested_value": 9.9})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_MUTATION_REJECTED"
    assert msg["status"] == "REJECTED"


def test_ws_hard_lock_then_mutate_is_nacked():
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 3.0, "set_lock": "HARD_LOCK"})
        ws.receive_json()  # cascade
        ws.send_json({"target_node": SKIN, "requested_value": 4.0})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_MUTATION_REJECTED"


def test_ws_malformed_frame_is_nacked_not_a_dropped_connection():
    """A frame that fails schema validation (missing field, wrong type, or an extra key — the
    protocol is extra='forbid') must NACK and keep the socket open, not raise an uncaught
    ValidationError out of the handler and kill the connection."""
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN})  # missing required requested_value
        msg = ws.receive_json()
        assert msg["event_type"] == "PARAMETER_MUTATION_REJECTED"
        assert msg["status"] == "REJECTED"

        ws.send_json({"target_node": SKIN, "requested_value": "not a number"})  # wrong type
        msg2 = ws.receive_json()
        assert msg2["event_type"] == "PARAMETER_MUTATION_REJECTED"

        ws.send_json({"target_node": SKIN, "requested_value": 3.0, "unexpected_field": 1})  # extra key
        msg3 = ws.receive_json()
        assert msg3["event_type"] == "PARAMETER_MUTATION_REJECTED"

        # the connection survived all three malformed frames — a normal mutation still works after
        ws.send_json({"target_node": SKIN, "requested_value": 3.0})
        msg4 = ws.receive_json()
        assert msg4["event_type"] == "PARAMETER_CASCADE_UPDATE"
        assert msg4["mutations_applied"][0]["value"] == 3.0


def test_ws_invalid_json_is_nacked_not_a_dropped_connection():
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_text("not valid json at all")
        msg = ws.receive_json()
        assert msg["event_type"] == "PARAMETER_MUTATION_REJECTED"

        ws.send_json({"target_node": SKIN, "requested_value": 3.0})
        msg2 = ws.receive_json()
        assert msg2["event_type"] == "PARAMETER_CASCADE_UPDATE"


def test_export_check_blocks_on_unknown_safety():
    c = _client()
    res = c.post("/export/check").json()
    assert res["status"] == "EXPORT_BLOCKED"
    assert "factor_of_safety" in res["unknowns"]


def test_export_step_enforces_gates_server_side():
    """The actual export endpoint must never hand back geometry when the gates are blocked — the
    advisory POST /export/check is voluntary, this is the real enforcement point for Inversion #1
    ('a missing safety input BLOCKS export, never a fabricated green light')."""
    c = _client()
    res = c.get("/export/step")
    assert res.status_code == 409
    body = res.json()
    assert body["status"] == "error"
    assert "factor_of_safety" in body["unknowns"]
    assert any("not engineer-reviewed" in r for r in body["reasons"])


def test_export_check_blocks_on_an_over_constrained_connection():
    # Phase 3 (2026-07-19, ENGINEERING_GRAPH_PLAN.md P3 topology-legality): connection_issues() already
    # fed the ADVISORY /validate self-check but a broken connection graph could still pass the EXPORT
    # gate silently — closed by folding connection_issues() into _all_gate_findings.
    #
    # 2026-07-21 update (foundations-audit H2 fix): apply_connection_op now rejects a connection whose
    # endpoint interface is ALREADY claimed by an existing connection, so the over-constrained state
    # below (wing's "root" interface mated twice) is now caught at add-time — fail-fast — instead of
    # being allowed through and only caught later by the export gate's connection_issues() walk. This
    # is strictly better (the copilot gets an immediate, actionable REJECTED instead of silently
    # building a broken graph it discovers is broken minutes later at export) but it does mean this
    # specific scenario can no longer reach the gate via the live REST path — the gate-level
    # connection_issues() over-constraint detection itself is still covered directly by
    # tests/subsystems/test_placement.py::test_over_constrained_connection_is_flagged_not_silently_dropped
    # (which builds the Connection objects directly, bypassing apply_connection_op's validation).
    c = _client()
    body = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bwb_fuselage"}).json()["instance_id"]
    wing = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel"}).json()["instance_id"]
    first = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wing, "a_interface": "root",
                                    "b_instance": body, "b_interface": "tip_right"}).json()
    assert first["status"] == "APPLIED"
    second = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wing, "a_interface": "root",
                                    "b_instance": body, "b_interface": "tip_left"}).json()
    assert second["status"] == "REJECTED"
    # the rejected second connection never reached the ledger, so export sees a clean, single-mate
    # graph — not blocked by a connection-legality finding (may still be blocked/eligible on other
    # grounds, e.g. no verdict yet; that's not what this test is about).
    res = c.post("/export/check").json()
    assert not any("do not meet" in r for r in res.get("reasons", []))


@pytest.mark.skipif(not importlib.util.find_spec("build123d"), reason="needs build123d")
def test_export_check_blocks_on_a_grossly_undersized_coupled_part():
    # Phase 3 (2026-07-19, ENGINEERING_GRAPH_PLAN.md P3 gross-error): a coarse cantilever-over-
    # bounding-box pre-check, reusing the ALREADY-VALIDATED closed-form oracle
    # (packages/truth_plane/solvers/cases.py). round_bar defaults to dia_mm=10/height_mm=300 (a thin
    # ~10x10x300mm bbox); a 50N coupling-derived force on PLA (yield 50 MPa) gives an analytical
    # FS≈0.56 under the worst-case cantilever reading — well past the FS<1.0 block threshold.
    c = TestClient(create_app())
    crank = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    c.post("/coupling_ops", json={"op": "add_coupling", "target_instance": crank,
                                  "relation": "force_from_pressure_area",
                                  "inputs": [{"name": "pressure_pa", "value": 1e8},
                                             {"name": "area_mm2", "value": 0.5}]})  # 1e8 * 0.5e-6 = 50 N
    res = c.post("/export/check").json()
    assert res["status"] == "EXPORT_BLOCKED"
    assert any("gross-error" in r and crank in r and "FS=" in r for r in res["reasons"])


@pytest.mark.skipif(not importlib.util.find_spec("build123d"), reason="needs build123d")
def test_export_check_does_not_gross_error_flag_a_reasonable_coupled_load():
    c = TestClient(create_app())
    crank = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    c.post("/coupling_ops", json={"op": "add_coupling", "target_instance": crank,
                                  "relation": "force_from_pressure_area",
                                  "inputs": [{"name": "pressure_pa", "value": 2e6},
                                             {"name": "area_mm2", "value": 0.5}]})  # 1 N — comfortably safe
    res = c.post("/export/check").json()
    assert not any("gross-error" in r for r in res["reasons"])


def test_export_step_does_not_block_on_a_different_instances_gross_error():
    """foundations-audit H3, 2026-07-21: the coupling/connection/gross-error extra_findings used to run
    over the WHOLE ledger regardless of which instance was being exported -- a grossly-undersized part
    ANYWHERE in the file blocked export of every other, fully-unrelated part too. Two round_bars in one
    file: "victim" gets the same undersized coupled load as
    test_export_check_blocks_on_a_grossly_undersized_coupled_part (a real, reachable gross-error
    finding); "keeper" has no coupling at all. Exporting "keeper" must never see victim's finding."""
    c = TestClient(create_app())
    victim = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    c.post("/coupling_ops", json={"op": "add_coupling", "target_instance": victim,
                                  "relation": "force_from_pressure_area",
                                  "inputs": [{"name": "pressure_pa", "value": 1e8},
                                             {"name": "area_mm2", "value": 0.5}]})  # same 50N as above
    keeper = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]

    # sanity: exporting the actually-bad instance DOES see the gross-error finding (proves the fixture
    # is real, not a false negative from something else entirely).
    victim_res = c.get(f"/export/step?instance_id={victim}").json()
    assert any("gross-error" in r and victim in r for r in victim_res["reasons"])

    # the fix under test: exporting the CLEAN, unrelated instance must not see it.
    keeper_res = c.get(f"/export/step?instance_id={keeper}").json()
    assert not any("gross-error" in r for r in keeper_res["reasons"])
    assert not any(victim in r for r in keeper_res["reasons"])


def test_export_check_does_not_gross_error_flag_an_uncoupled_part():
    # a part with NO coupling has no derived load to gross-error-check against — absent, not flagged
    # (same "absent vs unknown" precedent as packages/couplings/resolve.py::derived_load_n).
    c = TestClient(create_app())
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar", "instance_id": "crank"})
    res = c.post("/export/check").json()
    assert not any("gross-error" in r for r in res["reasons"])


def test_propose_without_key_returns_no_llm(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    res = _client().post("/propose", json={"intent": "make the skin 3 mm"}).json()
    assert res["no_llm"] is True
    assert res["provider"] == "none"
    assert res["deltas"] == []


def test_chat_without_key_streams_no_llm():
    res = _client().post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 200
    assert '"type": "no_llm"' in res.text


def test_chat_survives_an_unhandled_exception_mid_stream(monkeypatch):
    """foundations-audit follow-up (2026-07-22, live-reproduced): stream_chat's own internal
    try/except only covers ITS OWN streaming-fetch loop -- an exception raised anywhere ELSE inside
    it (a future bug in the post-stream tool-call processing, or any other unanticipated failure)
    used to propagate as a raw, uncaught exception out of the /chat generator with NO SSE frame at
    all -- not even the "error"+"done" pair this whole subsystem exists to guarantee. Confirmed via
    TestClient before this fix: the response delivered ZERO bytes and the client saw a raw
    RuntimeError, not a clean stream. This proves the fix holds the contract even for a failure mode
    stream_chat itself didn't anticipate."""
    import packages.agents.openrouter_provider as orp_module

    def broken_stream_chat(self, *, messages, ledger_json, project_id=None):
        yield ("token", "partial reply...")
        raise RuntimeError("simulated unexpected bug deep in stream_chat")

    monkeypatch.setattr(orp_module.OpenRouterDeltaProvider, "stream_chat", broken_stream_chat)

    c = _client()
    with c.stream("POST", "/chat", json={"messages": [{"role": "user", "content": "hi"}], "api_key": "x"}) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert '"type": "token"' in text
    assert '"type": "error"' in text and "simulated unexpected bug" in text
    assert '"type": "done"' in text
    # the error frame must come before done, and both must actually be present (not just anywhere
    # in an arbitrary byte soup) -- a crude but real ordering check via string position.
    assert text.index('"type": "error"') < text.index('"type": "done"')


# --- custom_geometry: /chat's SSE forward + ledger pointer write for propose_custom_geometry -----
# R3 CONFIRMED (Phase 5, 2026-08-06, HIGH): nothing anywhere exercised the `/chat` route's
# `elif kind == "custom_geometry":` branch -- neither the SSE forward nor the
# `state.log.append_generated_subsystem_attempt(...)` ledger write, individually or together. These
# mirror test_research_injection.py's "mock stream_chat directly, assert on res.text" pattern for the
# SSE half, and test_instance_op_clear_transform_succeeds_and_does_not_log_a_removal_event's own
# `app.state.sessions.only().log.events()` idiom for the ledger-write half.


def test_chat_dispatches_an_accepted_custom_geometry_event_and_appends_ledger_pointer(monkeypatch):
    from packages.ledger.events import EventKind
    from packages.subsystems.generated_registration import RegistrationResult

    result = RegistrationResult(
        accepted=True, outcome="registered", subsystem_name="finned_heat_spreader",
        attempt_id="attempt-123", rejected_floor=None, rejection_reason=None,
        sandbox_status="OK", volume_mm3=1234.5, bbox_mm=((0.0, 0.0, 0.0), (10.0, 10.0, 10.0)),
        model="deepseek/deepseek-chat", sha256="a" * 64,
    )

    def fake_stream_chat(self, *, messages, ledger_json, project_id=None):
        yield "custom_geometry", result
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )

    app = create_app()
    c = TestClient(app)
    res = c.post("/chat", json={"messages": [{"role": "user", "content": "make a heat spreader"}],
                                 "api_key": "x"})
    assert res.status_code == 200
    text = res.text

    # -- SSE forward half --
    assert '"type": "custom_geometry"' in text
    assert '"accepted": true' in text
    assert '"outcome": "registered"' in text
    assert '"subsystem_name": "finned_heat_spreader"' in text
    assert '"attempt_id": "attempt-123"' in text
    assert '"rejected_floor": null' in text
    assert '"rejection_reason": null' in text
    assert '"volume_mm3": 1234.5' in text
    assert '"type": "done"' in text

    # -- ledger-write half: a real GENERATED_SUBSYSTEM_ATTEMPT pointer event, durably appended --
    session = app.state.sessions.only()
    matches = [ev for ev in session.log.events() if ev.kind == EventKind.GENERATED_SUBSYSTEM_ATTEMPT]
    assert len(matches) == 1
    ev = matches[0]
    assert ev.payload["attempt_id"] == "attempt-123"
    assert ev.payload["sha256"] == "a" * 64
    assert ev.payload["subsystem_name"] == "finned_heat_spreader"
    assert ev.payload["model"] == "deepseek/deepseek-chat"
    assert ev.payload["outcome"] == "registered"
    assert ev.actor == "ai:deepseek/deepseek-chat"


def test_chat_dispatches_a_rejected_custom_geometry_event_without_a_ledger_write(monkeypatch):
    from packages.ledger.events import EventKind
    from packages.subsystems.generated_registration import RegistrationResult

    result = RegistrationResult(
        accepted=False, outcome="rejected", subsystem_name="",
        attempt_id="attempt-456", rejected_floor="ast_denylist",
        rejection_reason="disallowed import: os", sandbox_status=None,
        volume_mm3=None, bbox_mm=None, model="deepseek/deepseek-chat", sha256="b" * 64,
    )

    def fake_stream_chat(self, *, messages, ledger_json, project_id=None):
        yield "custom_geometry", result
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )

    app = create_app()
    c = TestClient(app)
    res = c.post("/chat", json={"messages": [{"role": "user", "content": "make something sketchy"}],
                                 "api_key": "x"})
    assert res.status_code == 200
    text = res.text

    # -- SSE forward half: a rejection is still forwarded, honestly, not swallowed --
    assert '"type": "custom_geometry"' in text
    assert '"accepted": false' in text
    assert '"outcome": "rejected"' in text
    assert '"attempt_id": "attempt-456"' in text
    assert '"rejected_floor": "ast_denylist"' in text
    assert '"rejection_reason": "disallowed import: os"' in text

    # -- ledger-write half: a REJECTED candidate must NOT get a per-project ledger pointer --
    # (register_generated_subsystem's own store.put(...) already durably records the rejected
    # attempt in the cross-project corpus; only an ACCEPTED candidate earns a project-local
    # GENERATED_SUBSYSTEM_ATTEMPT pointer event, per app.py's own kind == "custom_geometry" branch)
    session = app.state.sessions.only()
    matches = [ev for ev in session.log.events() if ev.kind == EventKind.GENERATED_SUBSYSTEM_ATTEMPT]
    assert matches == []


@pytest.mark.needs_kernel
@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="needs build123d")
def test_mesh_returns_real_geometry():
    res = _client().get("/mesh", params={"skin": 3.0}).json()
    assert len(res["positions"]) > 0 and len(res["positions"]) % 3 == 0
    assert len(res["indices"]) > 0 and len(res["indices"]) % 3 == 0


def test_mesh_times_out_cleanly_instead_of_hanging_on_a_wedged_build(monkeypatch):
    """foundations-audit F1 (2026-07-21, partial mitigation -- see _bounded_geometry_build's own
    docstring for the honest scope: this bounds a slow-but-finite build, it does NOT forcibly kill a
    genuinely wedged one). No real build123d/OCCT needed -- a fake, deliberately slow geometry_builder
    stands in for "the kernel never returns," and the timeout is dropped to make the test fast."""
    import dataclasses

    import packages.transport.app as app_module
    from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

    def _never_returns(ledger, instance_id):
        time.sleep(2.0)  # much longer than the test's own patched timeout below
        raise AssertionError("should have been abandoned by the timeout, not actually finished")

    monkeypatch.setattr(app_module, "_KERNEL_REGEN_TIMEOUT_S", 0.05)
    # SubsystemContext is a frozen dataclass -- swap the whole registry entry, not one field.
    slow_bracket = dataclasses.replace(get_subsystem("bracket"), geometry_builder=_never_returns)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, "bracket", slow_bracket)

    c = _client()
    res = c.get("/mesh")
    assert res.status_code == 504
    assert "timed out" in res.json()["error"]


def test_bounded_geometry_build_raises_timeout_error_on_a_wedged_build(monkeypatch):
    """Unit-level check of the mechanism _render_geometry/_render_geometry's callers rely on --
    /export/step's own timeout wiring isn't separately HTTP-tested here because reaching its
    geometry-build step at all requires first satisfying the export gate (a real analyzed verdict),
    which needs the real FEA solver this dev box doesn't have; the gate-scoping and gate-blocking
    behavior around it is already covered elsewhere (test_export_step_enforces_gates_server_side
    etc.) and /mesh (tested above) exercises the exact same _render_geometry -> _bounded_geometry_build
    path with none of that gate machinery in the way."""
    import packages.transport.app as app_module

    def _never_returns():
        time.sleep(2.0)
        raise AssertionError("should have been abandoned by the timeout, not actually finished")

    monkeypatch.setattr(app_module, "_KERNEL_REGEN_TIMEOUT_S", 0.05)
    with pytest.raises(TimeoutError):
        app_module._bounded_geometry_build(_never_returns)


def test_mesh_features_times_out_cleanly_instead_of_hanging_on_a_wedged_build(monkeypatch):
    """F1 follow-up (2026-07-21): /mesh/features is fired in the SAME Promise.all as /mesh on every
    live-drag tick (Viewport.tsx's pump()) -- it was missed in the original F1 pass and called
    geometry_builder directly with no timeout, an unbounded hole in an otherwise-bounded mitigation.
    Wrapped WHOLE (like /mesh wraps render_assembly whole) because there is no per-instance seam to
    bound: instance_world_offsets() can call a geometry_builder itself (assembly.py's own
    _y_extent_mm, for an auto-laid-out instance with no explicit transform) BEFORE
    list_pickable_features' per-instance loop ever runs -- confirmed by reproducing this exact
    single-instance ledger wedging in the offset phase, not the loop, when this fix was first
    attempted with a narrower per-instance seam."""
    import dataclasses

    import packages.transport.app as app_module
    from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

    def _never_returns(ledger, instance_id):
        time.sleep(2.0)
        raise AssertionError("should have been abandoned by the timeout, not actually finished")

    monkeypatch.setattr(app_module, "_KERNEL_REGEN_TIMEOUT_S", 0.05)
    slow_bracket = dataclasses.replace(get_subsystem("bracket"), geometry_builder=_never_returns)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, "bracket", slow_bracket)

    c = _client()
    start = time.perf_counter()
    res = c.get("/mesh/features")
    elapsed = time.perf_counter() - start
    assert res.status_code == 504
    assert "timed out" in res.json()["error"]
    assert elapsed < 1.5  # bounded by the patched 0.05s timeout, not the fake builder's 2s sleep


@pytest.mark.needs_kernel
@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="needs build123d")
def test_mesh_features_returns_bracket_hole_points():
    res = _client().get("/mesh/features").json()
    features = res["features"]
    assert len(features) >= 1
    bore = next(f for f in features if f["tag"].startswith("hole["))
    assert bore["instance_id"] == "root"
    assert len(bore["point"]) == 3
    assert bore["meta"]["dia"] == 6.0  # bracket's default hole_diameter_mm


# --- FeatureOp: AI-proposed hole/pocket/slot cuts, human-accepted via POST /feature_ops ----------


def test_chat_proposal_includes_feature_ops(monkeypatch):
    """The /chat SSE `proposal` event must carry `feature_ops` alongside `deltas` (extended,
    2026-07-04), serialized the same way (`[fo.model_dump(mode='json') ...]`)."""
    from packages.ledger.deltas import DeltaProposal, FeatureOp

    def fake_stream_chat(self, *, messages, ledger_json, project_id=None):
        yield "proposal", DeltaProposal(
            feature_ops=[FeatureOp(op="add_feature", instance_id="root", kind="hole",
                                   shape="circle", dia_mm=5.0, through=True)]
        )
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )
    res = _client().post("/chat", json={"messages": [{"role": "user", "content": "add a hole"}], "api_key": "x"})
    assert res.status_code == 200
    assert '"type": "proposal"' in res.text
    assert '"feature_ops"' in res.text
    assert '"op": "add_feature"' in res.text
    assert '"instance_id": "root"' in res.text


def test_feature_op_rejects_unknown_instance_without_needing_geometry():
    # short-circuits before any build123d call -> no needs_kernel marker required
    res = _client().post("/feature_ops", json={
        "op": "add_feature", "instance_id": "nope", "kind": "hole", "shape": "circle",
        "dia_mm": 5.0, "depth_mm": 1.0,
    }).json()
    assert res["ok"] is False
    assert res["status"] == "REJECTED"
    assert res["feature"] is None


@pytest.mark.needs_kernel
@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="needs build123d")
def test_feature_op_add_applies_and_persists_to_ledger():
    c = _client()
    res = c.post("/feature_ops", json={
        "op": "add_feature", "instance_id": "root", "kind": "hole", "shape": "circle",
        "dia_mm": 5.0, "through": True,
    }).json()
    assert res["ok"] is True
    assert res["status"] == "APPLIED"
    assert res["instance_id"] == "root"
    assert res["feature"]["depth_mm"] > 0
    fid = res["feature"]["id"]

    led = c.get("/ledger").json()
    feats = led["instances"]["root"]["cut_features"]
    assert any(f["id"] == fid for f in feats)


@pytest.mark.needs_kernel
@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="needs build123d")
def test_feature_op_oversized_is_conflict_and_not_committed():
    c = _client()
    res = c.post("/feature_ops", json={
        "op": "add_feature", "instance_id": "root", "kind": "hole", "shape": "circle",
        "dia_mm": 500.0, "depth_mm": 1.0,
    }).json()
    assert res["ok"] is False
    assert res["status"] == "CONFLICT"
    led = c.get("/ledger").json()
    assert led["instances"]["root"]["cut_features"] == []


@pytest.mark.needs_kernel
@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="needs build123d")
def test_feature_op_replay_from_log_reconstructs_cut_feature():
    """Event-sourcing correctness: the FEATURE_OP fact alone (no live session state) must be enough
    for a cold replay to reconstruct the same cut_features."""
    app = create_app()
    c = TestClient(app)
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    res = c.post("/feature_ops", json={
        "op": "add_feature", "instance_id": "root", "kind": "hole", "shape": "circle",
        "dia_mm": 5.0, "through": True,
    }).json()
    assert res["ok"] is True
    fid = res["feature"]["id"]

    session = app.state.sessions.only()
    replayed = session.log.fold()  # re-runs `replay()` over the raw fact log from scratch
    assert any(f.id == fid for f in replayed.instances["root"].cut_features)


# --- InstanceOp: AI-proposed assembly composition, human-accepted via POST /instance_ops ---------


def test_chat_proposal_includes_instance_ops(monkeypatch):
    """The /chat SSE `proposal` event must carry `instance_ops` alongside `deltas`/`feature_ops`,
    serialized the same way (`[io.model_dump(mode='json') ...]`)."""
    from packages.ledger.deltas import DeltaProposal, InstanceOp

    def fake_stream_chat(self, *, messages, ledger_json, project_id=None):
        yield "proposal", DeltaProposal(
            instance_ops=[InstanceOp(op="add_instance", subsystem_type="enclosure")]
        )
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )
    res = _client().post("/chat", json={"messages": [{"role": "user", "content": "add an enclosure"}], "api_key": "x"})
    assert res.status_code == 200
    assert '"type": "proposal"' in res.text
    assert '"instance_ops"' in res.text
    assert '"op": "add_instance"' in res.text
    assert '"subsystem_type": "enclosure"' in res.text


def test_chat_proposal_includes_region_ops(monkeypatch):
    """The /chat SSE `proposal` event must carry `region_ops` alongside `deltas`/`feature_ops`/
    `instance_ops`, serialized the same way (`[ro.model_dump(mode='json') ...]`). Regression for the
    finding that the handler hand-listed every other op-list field but omitted `region_ops` entirely,
    silently dropping any model-proposed RegionOp before it reached the SSE frame (and thus the
    frontend, whose ChatEvent["proposal"] type and Chat.tsx both already expect this key)."""
    from packages.ledger.deltas import DeltaProposal, RegionOp

    def fake_stream_chat(self, *, messages, ledger_json, project_id=None):
        yield "proposal", DeltaProposal(
            region_ops=[RegionOp(op="add_region", host_instance="root", kind="keep_out",
                                  label="battery_pack_reserve", x_mm=-15, y_mm=-10, z_mm=0,
                                  dx_mm=25, dy_mm=30, dz_mm=15)]
        )
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )
    res = _client().post("/chat", json={"messages": [{"role": "user", "content": "reserve space for the battery"}], "api_key": "x"})
    assert res.status_code == 200
    assert '"type": "proposal"' in res.text
    assert '"region_ops"' in res.text
    assert '"op": "add_region"' in res.text
    assert '"label": "battery_pack_reserve"' in res.text


def test_chat_proposal_includes_envelope_ops(monkeypatch):
    """The /chat SSE `proposal` event must carry `envelope_ops` alongside `deltas`/`feature_ops`/
    `instance_ops`/`fit_ops`/`region_ops`, serialized the same way (`[eo.model_dump(mode='json') ...]`).
    Regression for R2's CONFIRMED finding (gearbox-housing-generation Phase 4): `EnvelopeOp` existed as
    a model but was never added as a `DeltaProposal` field nor forwarded here, so the model had no
    tool-use path that could ever emit a `wrap_group`/`unwrap_group`/`resync_envelope` call despite
    `_housing_pacing_section` instructing it to propose exactly that — mirrors
    `test_chat_proposal_includes_region_ops` above exactly, one field over."""
    from packages.ledger.deltas import DeltaProposal, EnvelopeOp

    def fake_stream_chat(self, *, messages, ledger_json, project_id=None):
        yield "proposal", DeltaProposal(
            envelope_ops=[EnvelopeOp(op="wrap_group", housing_instance="housing_1",
                                      member_instance_ids=["gear_1", "gear_2"])]
        )
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )
    res = _client().post("/chat", json={"messages": [{"role": "user", "content": "wrap the gear cluster"}], "api_key": "x"})
    assert res.status_code == 200
    assert '"type": "proposal"' in res.text
    assert '"envelope_ops"' in res.text
    assert '"op": "wrap_group"' in res.text
    assert '"housing_instance": "housing_1"' in res.text


def test_instance_op_rejects_unknown_subsystem_type():
    res = _client().post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spaceship"}).json()
    assert res["ok"] is False
    assert res["status"] == "REJECTED"
    assert res["instance"] is None


def test_instance_op_add_applies_and_persists_to_ledger_and_outliner():
    c = _client()
    res = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "enclosure"}).json()
    assert res["ok"] is True
    assert res["status"] == "APPLIED"
    iid = res["instance_id"]
    assert res["instance"]["subsystem_type"] == "enclosure"

    led = c.get("/ledger").json()
    assert iid in led["instances"]
    # GET /instances (the outliner's data source) picks it up automatically — same ledger read
    rows = c.get("/instances").json()["instances"]
    assert any(r["id"] == iid and r["subsystem_type"] == "enclosure" for r in rows)


def test_instance_op_add_explicit_id_collision_is_rejected():
    c = _client()
    first = c.post("/instance_ops", json={
        "op": "add_instance", "subsystem_type": "enclosure", "instance_id": "enc_x",
    }).json()
    assert first["ok"] is True
    dup = c.post("/instance_ops", json={
        "op": "add_instance", "subsystem_type": "enclosure", "instance_id": "enc_x",
    }).json()
    assert dup["ok"] is False
    assert dup["status"] == "REJECTED"


def test_instance_op_remove_childless_root_is_allowed():
    """2026-07-04: removing a childless root returns to an empty project — this is what makes
    "undo my very first add_instance" work, since that first instance IS the root."""
    c = _client()
    root_id = c.get("/ledger").json()["root_id"]
    res = c.post("/instance_ops", json={"op": "remove_instance", "instance_id": root_id}).json()
    assert res["ok"] is True
    assert res["status"] == "APPLIED"
    assert c.get("/instances").json()["instances"] == []


def test_instance_op_remove_root_with_children_is_rejected():
    c = _client()
    root_id = c.get("/ledger").json()["root_id"]
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "standoff", "parent_id": root_id})
    res = c.post("/instance_ops", json={"op": "remove_instance", "instance_id": root_id}).json()
    assert res["ok"] is False
    assert res["status"] == "REJECTED"


def test_instance_op_add_then_remove_round_trips():
    c = _client()
    added = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "standoff"}).json()
    iid = added["instance_id"]
    removed = c.post("/instance_ops", json={"op": "remove_instance", "instance_id": iid}).json()
    assert removed["ok"] is True
    assert removed["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert iid not in led["instances"]


def test_instance_op_remove_surfaces_removed_coupling_and_region_ids():
    """2026-08-05 cascade-visibility fix (root cause #3): apply_instance_op already computed
    removed_connection_ids/removed_coupling_ids for the event log, but the REST response never
    returned them, so the model had no way to notice a remove_instance call just destroyed a
    coupling or a region. All FIVE cascade id lists are now surfaced on the response — non-empty
    only for the cascades that actually applied, `[]` (not omitted) for the rest."""
    c = TestClient(create_app())
    crank = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    coupling = c.post("/coupling_ops", json={"op": "add_coupling", "target_instance": crank,
                                  "relation": "force_from_pressure_area",
                                  "inputs": [{"name": "pressure_pa", "value": 2e6},
                                             {"name": "area_mm2", "value": 0.5}]}).json()
    assert coupling["ok"] is True
    region = c.post("/region_ops", json={"op": "add_region", "host_instance": crank, "kind": "keep_out",
                                          "label": "wiring_channel", "x_mm": 0, "y_mm": 0, "z_mm": 0,
                                          "dx_mm": 10, "dy_mm": 10, "dz_mm": 10}).json()
    assert region["ok"] is True

    res = c.post("/instance_ops", json={"op": "remove_instance", "instance_id": crank}).json()
    assert res["ok"] is True
    assert res["removed_coupling_ids"] == [coupling["coupling_id"]]
    assert res["removed_region_ids"] == [region["region_id"]]
    # unrelated cascade lists stay present-but-empty, never omitted
    assert res["removed_connection_ids"] == []
    assert res["removed_fit_binding_ids"] == []
    assert res["removed_join_annotation_ids"] == []


def test_instance_op_add_and_move_leave_cascade_ids_empty():
    c = TestClient(create_app())
    added = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "standoff"}).json()
    assert added["removed_coupling_ids"] == []
    assert added["removed_region_ids"] == []
    assert added["removed_fit_binding_ids"] == []
    assert added["removed_join_annotation_ids"] == []
    iid = added["instance_id"]
    moved = c.post("/instance_ops", json={
        "op": "move_instance", "instance_id": iid, "x_mm": 5.0, "y_mm": 5.0, "z_mm": 5.0,
    }).json()
    assert moved["removed_coupling_ids"] == []
    assert moved["removed_region_ids"] == []


def test_instance_op_remove_cascade_region_is_durably_persisted_and_does_not_resurrect_on_id_reuse():
    """R3-test-honesty (2026-08-05, HIGH, live-reproduced): the response-only test above
    (test_instance_op_remove_surfaces_removed_coupling_and_region_ids) checked `removed_region_ids`
    on the REST response but never called GET /ledger afterward — so it never actually proved the
    cascade was PERSISTED to the event log (vs. just correctly computed and reported). This is the
    transport-layer analogue of tests/ledger/test_instance_ops.py::
    test_remove_instance_cascades_region_and_reused_id_does_not_inherit_it, run against the live
    FastAPI app (state.ledger() == the replayed event log) instead of the pure function — the layer
    that actually serves the running copilot."""
    c = TestClient(create_app())
    host = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    region = c.post("/region_ops", json={"op": "add_region", "host_instance": host, "kind": "keep_out",
                                          "label": "wiring_channel", "x_mm": 0, "y_mm": 0, "z_mm": 0,
                                          "dx_mm": 10, "dy_mm": 10, "dz_mm": 10}).json()
    rid = region["region_id"]
    assert any(r["id"] == rid for r in c.get("/ledger").json()["regions"])

    res = c.post("/instance_ops", json={"op": "remove_instance", "instance_id": host}).json()
    assert res["removed_region_ids"] == [rid]

    led = c.get("/ledger").json()
    assert led["regions"] == [], (
        "cascaded Region must be durably removed from the replayed ledger, not just reported in the "
        "response"
    )

    # id-reuse regression: re-adding the same subsystem type reuses the freed id (lowest-free) — the
    # stale region must NOT silently re-attach to this new, unrelated instance.
    host2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    assert host2 == host
    assert c.get("/ledger").json()["regions"] == []


def test_instance_op_remove_cascade_fit_binding_is_durably_persisted_and_does_not_resurrect_on_id_reuse():
    """Same durable-persistence + id-reuse proof as the region test above, for FitBindings (removed
    when either connector_instance or host_instance is the removed instance) — R3-test-honesty."""
    c = TestClient(create_app())
    post_id = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_post",
                                             "instance_id": "post1"}).json()["instance_id"]
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spar_joiner_sleeve",
                                  "instance_id": "sleeve1"})
    fit = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": "sleeve1",
                                   "host_instance": post_id, "clearance_mm": 0.2}).json()
    fid = fit["fit_id"]
    assert any(f["id"] == fid for f in c.get("/ledger").json()["fit_bindings"])

    res = c.post("/instance_ops", json={"op": "remove_instance", "instance_id": post_id}).json()
    assert res["removed_fit_binding_ids"] == [fid]

    led = c.get("/ledger").json()
    assert led["fit_bindings"] == [], (
        "cascaded FitBinding must be durably removed from the replayed ledger, not just reported in "
        "the response"
    )

    # id-reuse regression
    post2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_post",
                                          "instance_id": "post1"}).json()
    assert post2["instance_id"] == post_id
    assert c.get("/ledger").json()["fit_bindings"] == []


def test_instance_op_remove_cascade_join_annotation_via_cascaded_connection_is_durably_persisted():
    """The one-hop-further cascade: removing an instance cascade-removes its Connections, which in
    turn cascade-removes any JoinAnnotation attached to those Connections. Proves the SAME
    durably-persisted + id-reuse-safe guarantee two hops deep, at the REST layer — R3-test-honesty."""
    c = TestClient(create_app())
    box = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "enclosure",
                                        "instance_id": "box"}).json()["instance_id"]
    # no explicit instance_id for the bracket -- it must get an AUTO id ("lbracket_1") for the
    # id-reuse regression below to be meaningful (explicit ids are never "reused", only auto ids are)
    brk = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "lbracket"}).json()["instance_id"]
    conn = c.post("/connection_ops", json={"op": "add_connection", "a_instance": brk,
                                            "a_interface": "wall_mount", "b_instance": box,
                                            "b_interface": "right"}).json()
    cid = conn["connection_id"]
    jid = c.post("/join_annotation_ops", json={"op": "add_join_annotation", "connection_id": cid,
                                               "method": "bolted"}).json()["join_id"]
    assert any(j["id"] == jid for j in c.get("/ledger").json()["join_annotations"])

    res = c.post("/instance_ops", json={"op": "remove_instance", "instance_id": brk}).json()
    assert res["removed_connection_ids"] == [cid]
    assert res["removed_join_annotation_ids"] == [jid]

    led = c.get("/ledger").json()
    assert led["connections"] == []
    assert led["join_annotations"] == [], (
        "cascaded JoinAnnotation (via the cascaded Connection) must be durably removed from the "
        "replayed ledger, not just reported in the response"
    )

    # id-reuse regression: both the instance id AND the connection id it re-forms get reused
    brk2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "lbracket"}).json()["instance_id"]
    assert brk2 == brk
    conn2 = c.post("/connection_ops", json={"op": "add_connection", "a_instance": brk2,
                                             "a_interface": "wall_mount", "b_instance": box,
                                             "b_interface": "right"}).json()
    assert conn2["connection_id"] == cid
    assert c.get("/ledger").json()["join_annotations"] == []


def test_instance_op_remove_surfaces_scrubbed_wraps_instance_ids(monkeypatch):
    """2026-08-06 fix (R2 CONFIRMED, low): `scrubbed_wraps_instance_ids` is a SIXTH cascade output
    `apply_instance_op` computes on remove_instance (packages/ledger/apply.py) — ids of housing
    instances whose `wraps` (packages/ledger/schema.py::Instance.wraps) just got the removed
    instance id scrubbed out of it. Unlike its five `removed_*_ids` siblings right next to it in the
    same REST response (see test_instance_op_remove_surfaces_removed_coupling_and_region_ids above),
    it was silently never echoed by POST /instance_ops's JSON response, so a caller had no way to
    learn from the response alone that a housing's `wraps` list was quietly rewritten as a side
    effect — this is the transport-layer analogue of
    tests/ledger/test_instance_ops.py::test_remove_instance_scrubs_wraps_and_reused_id_does_not_reattach.

    Sets up the `wraps` precondition via the real /envelope_ops wrap_group route, but with REDIS_URL
    set (mirrors tests/backend/test_analysis_api.py::
    test_queued_analyze_records_status_durably_across_the_process_boundary's own "import jobs BEFORE
    setting REDIS_URL, monkeypatch .send to a no-op" shape) so this test never needs real OCCT/
    build123d work — `apply_envelope_op`'s `wraps` mutation itself is cheap, ordinary ledger state,
    entirely separate from the (queued-away-here) derivation compute."""
    import packages.truth_plane.jobs as jobs_module
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://fake/0")  # makes /envelope_ops take the queued branch
    monkeypatch.setattr(jobs_module.run_envelope_derivation, "send",
                        lambda *a, **k: None)  # don't actually enqueue

    c = TestClient(create_app())
    housing = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "standoff",
                                             "instance_id": "housing_1"}).json()
    assert housing["ok"] is True
    member = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "standoff",
                                            "instance_id": "member_1"}).json()
    assert member["ok"] is True

    wrapped = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": "housing_1", "member_instance_ids": ["member_1"],
    }).json()
    assert wrapped["ok"] is True and wrapped["instance"]["wraps"] == ["member_1"]
    assert c.get("/ledger").json()["instances"]["housing_1"]["wraps"] == ["member_1"]

    res = c.post("/instance_ops", json={"op": "remove_instance", "instance_id": "member_1"}).json()
    assert res["ok"] is True
    assert res["scrubbed_wraps_instance_ids"] == ["housing_1"]
    # unrelated cascade lists stay present-but-empty, never omitted (same shape as the five siblings)
    assert res["removed_connection_ids"] == []
    assert res["removed_coupling_ids"] == []
    assert res["removed_region_ids"] == []
    assert res["removed_fit_binding_ids"] == []
    assert res["removed_join_annotation_ids"] == []
    # 2026-08-06 fix: the scrub now DOES survive a fresh ledger reload/replay, closing the gap the
    # note above used to document — `create_instance_op`'s remove_instance branch reuses
    # EventKind.ENVELOPE_WRAPPED (the same event `wrap_group` itself appends) to persist each scrubbed
    # housing's NEW (post-scrub) `wraps` list, mirroring the five `removed_*_ids` siblings' own
    # append_*_removed pattern. `GET /ledger` always re-folds from the event log (state.ledger() ==
    # self.log.fold(...)), so this assertion IS a real durability check, not just a same-request echo.
    assert c.get("/ledger").json()["instances"]["housing_1"]["wraps"] == []


def test_instance_op_clear_transform_succeeds_and_does_not_log_a_removal_event():
    """The op-type branching fix under test: `clear_transform` must NOT fall into remove_instance's
    cascade branch (which would log bogus CONNECTION_REMOVED/COUPLING_REMOVED/INSTANCE_REMOVED
    events for an instance that was never actually removed) — this is the bug a naive `else:
    <assume remove_instance>` branch would have reintroduced."""
    app = create_app()
    c = TestClient(app)
    added = c.post("/instance_ops", json={
        "op": "add_instance", "subsystem_type": "standoff", "x_mm": 1.0, "y_mm": 2.0, "z_mm": 3.0,
    }).json()
    iid = added["instance_id"]
    assert added["instance"]["transform"] is not None

    res = c.post("/instance_ops", json={"op": "clear_transform", "instance_id": iid}).json()
    assert res["ok"] is True
    assert res["status"] == "APPLIED"
    assert res["instance"]["transform"] is None

    led = c.get("/ledger").json()
    assert iid in led["instances"]                       # never removed
    assert led["instances"][iid]["transform"] is None    # reverted to pure mate-based auto-layout

    from packages.ledger.events import EventKind
    session = app.state.sessions.only()
    kinds = [ev.kind for ev in session.log.events()]
    assert EventKind.INSTANCE_REMOVED not in kinds
    assert EventKind.CONNECTION_REMOVED not in kinds
    assert EventKind.COUPLING_REMOVED not in kinds


def test_instance_op_clear_transform_unknown_instance_id_rejected():
    res = _client().post("/instance_ops", json={
        "op": "clear_transform", "instance_id": "ghost",
    }).json()
    assert res["ok"] is False
    assert res["status"] == "REJECTED"


def test_instance_op_move_applies_and_persists_new_transform_with_previous_snapshot():
    """THE CONFIRMED BUG's end-to-end proof at the transport layer: a move_instance InstanceOp is now
    a legal thing to say, applies, persists to the ledger, and the response carries BOTH the new
    ("instance") and prior ("previous_instance") state for the frontend's Undo."""
    c = _client()
    added = c.post("/instance_ops", json={
        "op": "add_instance", "subsystem_type": "standoff",
        "x_mm": 1.0, "y_mm": 2.0, "z_mm": 3.0,
    }).json()
    assert added["ok"] is True
    iid = added["instance_id"]

    moved = c.post("/instance_ops", json={
        "op": "move_instance", "instance_id": iid, "x_mm": 50.0, "y_mm": 60.0, "z_mm": 70.0,
    }).json()
    assert moved["ok"] is True
    assert moved["status"] == "APPLIED"
    assert moved["instance"]["transform"]["x_mm"] == 50.0
    assert moved["instance"]["transform"]["y_mm"] == 60.0
    assert moved["instance"]["transform"]["z_mm"] == 70.0
    assert moved["previous_instance"]["transform"]["x_mm"] == 1.0
    assert moved["previous_instance"]["transform"]["y_mm"] == 2.0
    assert moved["previous_instance"]["transform"]["z_mm"] == 3.0

    led = c.get("/ledger").json()
    assert led["instances"][iid]["transform"]["x_mm"] == 50.0


def test_instance_op_move_rejects_partial_position():
    c = _client()
    added = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "standoff"}).json()
    iid = added["instance_id"]
    res = c.post("/instance_ops", json={
        "op": "move_instance", "instance_id": iid, "x_mm": 5.0, "y_mm": 6.0,
    }).json()
    assert res["ok"] is False
    assert res["status"] == "REJECTED"


def test_instance_op_move_unknown_instance_id_rejected():
    res = _client().post("/instance_ops", json={
        "op": "move_instance", "instance_id": "ghost", "x_mm": 1.0, "y_mm": 1.0, "z_mm": 1.0,
    }).json()
    assert res["ok"] is False
    assert res["status"] == "REJECTED"
    assert res["previous_instance"] is None


def test_instance_op_move_replay_from_log_reconstructs_new_transform():
    """Event-sourcing correctness for move_instance: a cold replay from the raw log alone must
    reconstruct the moved-to transform, not just the in-memory session state."""
    app = create_app()
    c = TestClient(app)
    added = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "enclosure"}).json()
    iid = added["instance_id"]
    moved = c.post("/instance_ops", json={
        "op": "move_instance", "instance_id": iid, "x_mm": 11.0, "y_mm": 22.0, "z_mm": 33.0,
    }).json()
    assert moved["ok"] is True

    session = app.state.sessions.only()
    replayed = session.log.fold()
    assert replayed.instances[iid].transform.x_mm == 11.0
    assert replayed.instances[iid].transform.y_mm == 22.0
    assert replayed.instances[iid].transform.z_mm == 33.0


def test_instance_op_replay_from_log_reconstructs_instance():
    """Event-sourcing correctness: reuses the EXISTING INSTANCE_ADDED/INSTANCE_REMOVED facts (not a
    new parallel fact kind) — a cold replay from the raw log alone must reconstruct the same instance."""
    app = create_app()
    c = TestClient(app)
    res = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "enclosure"}).json()
    assert res["ok"] is True
    iid = res["instance_id"]

    session = app.state.sessions.only()
    replayed = session.log.fold()  # re-runs `replay()` over the raw fact log from scratch
    assert iid in replayed.instances
    assert replayed.instances[iid].subsystem_type == "enclosure"

    # and the event kind used is the pre-existing INSTANCE_ADDED, not a new parallel fact kind
    from packages.ledger.events import EventKind
    kinds = [ev.kind for ev in session.log.events()]
    assert EventKind.INSTANCE_ADDED in kinds


def test_params_endpoint_carries_invariant_valid_ranges():
    # 2026-07-19: /params must include a per-param invariant-valid [valid_min, valid_max] clamp so the
    # frontend slider can't be dragged into a CONFLICT. bwb_fuselage.blend_taper_mm at span=600 must
    # clamp to ~[0,300] (span/2), tighter than its recommended [0,1500].
    c = TestClient(create_app())
    r = c.post("/instances", json={"subsystem_type": "bwb_fuselage"}).json()
    iid = r["instance_id"]
    span_node = f"instances.{iid}.params.span_mm"
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": span_node, "requested_value": 600.0})
        ws.receive_json()
    rows = {row["node"]: row for row in c.get("/params").json()["params"]}
    bt = rows[f"instances.{iid}.params.blend_taper_mm"]
    assert bt["min"] == 0.0 and bt["max"] == 1500.0          # advisory recommended, unchanged
    assert bt["valid_min"] == 0.0 and 299.0 <= bt["valid_max"] <= 300.0  # physically-valid clamp


def test_ws_mutation_response_carries_refreshed_valid_ranges():
    # the WS cascade response must carry refreshed valid ranges for EVERY geometry param, so a drag
    # on span_mm live-updates blend_taper_mm's slider clamp without a /params round trip.
    c = TestClient(create_app())
    r = c.post("/instances", json={"subsystem_type": "bwb_fuselage"}).json()
    iid = r["instance_id"]
    span_node = f"instances.{iid}.params.span_mm"
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": span_node, "requested_value": 600.0})
        resp = ws.receive_json()
        assert resp["event_type"] == "PARAMETER_CASCADE_UPDATE"
        vr = {v["node"]: v for v in resp["valid_ranges"]}
        bt = vr[f"instances.{iid}.params.blend_taper_mm"]
        assert 299.0 <= bt["valid_max"] <= 300.0
        # raising span widens blend_taper's valid max, live in the next response
        ws.send_json({"target_node": span_node, "requested_value": 1600.0})
        resp2 = ws.receive_json()
        vr2 = {v["node"]: v for v in resp2["valid_ranges"]}
        bt2 = vr2[f"instances.{iid}.params.blend_taper_mm"]
        assert 799.0 <= bt2["valid_max"] <= 800.0


def test_bare_param_name_is_qualified_to_the_active_instance():
    # 2026-07-19: the copilot sometimes emits a BARE param name instead of the instance-qualified
    # path; that used to hard-reject as "unknown node" and silently drop the whole size step (seen
    # live building a BWB). A bare name matching the ACTIVE instance's param must now apply.
    c = TestClient(create_app())
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bwb_fuselage", "instance_id": "centerbody"})
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "sweep_deg", "requested_value": 12.0})  # BARE — no dots
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_CASCADE_UPDATE"  # resolved + applied, not rejected
    assert c.get("/ledger").json()["instances"]["centerbody"]["params"]["sweep_deg"]["value"] == 12.0


def test_bare_name_that_is_not_a_param_of_the_active_part_still_rejects():
    # the qualification must ONLY rescue an unambiguous match — a bare name that isn't a real param
    # must still reject, never get silently rewritten onto the wrong thing.
    c = TestClient(create_app())
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bwb_fuselage", "instance_id": "cb"})
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "not_a_real_param", "requested_value": 5.0})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_MUTATION_REJECTED"


# --- Defect 2 regression (2026-08-03): a whole-assembly export must gate on EVERY buildable instance ---

def _fake_analyze_ok(params, material_name, load_n, subsystem_name="bracket", cut_features=None):
    # mirrors tests/backend/test_analysis_api.py's own `_fake_analyze` (solver faked; build123d/export
    # is real on this host) -- a real-shaped, PASSING verdict with no gmsh/CalculiX dependency.
    return Verdict(geometry_signature=signature_from_params(params, geometry_params=tuple(params.keys())),
                   fingerprint=fingerprint(),
                   factor_of_safety=4.0, mesh_converged=True, watertight=True, min_wall_ok=True,
                   solver_seconds=1.0)


def test_export_step_whole_assembly_gates_on_every_buildable_instance(monkeypatch):
    """Before this fix, `/export/step` with `instance_id` omitted evaluated the export gate against
    ONLY `state.active_instance()` — but `_render_geometry` composes EVERY instance in the ledger into
    the exported file the moment it holds more than one (`render_assembly`). Sign off ONE bracket
    ('good'), leave a second ('bad') never analyzed (an unknown FS) -- the whole-assembly export must
    block on 'bad', not silently ship it alongside 'good'."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _fake_analyze_ok)
    c = TestClient(create_app())
    good = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bracket"}).json()["instance_id"]
    bad = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bracket"}).json()["instance_id"]
    c.post(f"/instances/{good}/activate")  # 'good' becomes the ACTIVE instance /analyze/ /signoff target

    r = c.post("/analyze").json()
    assert r["status"] == "done" and r["verdict"]["factor_of_safety"] == 4.0
    c.post("/signoff", params={"reviewer": "pe@example.com"})

    # sanity: 'good' alone really is fully eligible (proves this isn't a false negative from something
    # else entirely) — a REAL exported STEP file comes back.
    assert c.get(f"/export/step?instance_id={good}").status_code == 200
    # sanity: 'bad' alone really is blocked (never analyzed — an honest unknown FS). An EXPLICIT
    # instance_id is the pre-existing, unprefixed single-instance format (unchanged by this fix).
    bad_res = c.get(f"/export/step?instance_id={bad}")
    assert bad_res.status_code == 409
    assert "factor_of_safety" in bad_res.json()["unknowns"]

    # THE fix under test: a whole-assembly export (no instance_id, 2 instances in the file) must block
    # on 'bad' even though the ACTIVE instance ('good') is itself fully signed off and eligible.
    whole_res = c.get("/export/step")
    assert whole_res.status_code == 409
    body = whole_res.json()
    assert any(f"{bad}: factor_of_safety" in u for u in body["unknowns"])
    assert any(bad in r for r in body["reasons"])

    # /export/check (the advisory twin) must never diverge from what /export/step actually enforces.
    assert c.post("/export/check").json()["status"] == "EXPORT_BLOCKED"


def test_export_step_whole_assembly_single_instance_case_is_unchanged():
    # the single-instance file (the overwhelming common case) must behave BYTE-FOR-BYTE as before this
    # fix — no aggregation machinery kicks in when there's nothing to aggregate over.
    c = _client()  # bootstraps exactly one instance ("root")
    res = c.get("/export/step")
    assert res.status_code == 409
    body = res.json()
    assert "factor_of_safety" in body["unknowns"]           # NOT prefixed with an instance id
    assert any("not engineer-reviewed" in r for r in body["reasons"])


# --- Defect 3 regression (2026-08-03): the grounded verdict path must use the ledger's REAL material ---

def test_analyze_and_export_use_the_ledgers_real_material_not_a_hardcoded_pla(monkeypatch):
    """/analyze's material default AND resolved_ledger()'s own `material=` argument to
    `ledger_with_derived()` both used to be the literal "PLA" regardless of the design's OWN
    `domains.structure.material_profile` (the same field the coarse structural pre-check,
    `_iter_coarse_cantilever_fs`, already reads) — change the project's material to ABS and BOTH
    hardcodes used to keep silently agreeing with EACH OTHER on the wrong "PLA" case (never surfacing
    as a blocked gate, since the two literals matched each other; the actual bug was a silently
    wrong-material verdict, not a blocked one). Pin: /analyze must default to (and tag its cached
    verdict with) the REAL "ABS" profile, and the export gate's own resolved-derived lookup must then
    find that SAME ABS-keyed verdict — not go looking for a "PLA" one that was never solved."""
    seen_material: list[str] = []

    def _fake_analyze_records_material(params, material_name, load_n, subsystem_name="bracket", cut_features=None):
        seen_material.append(material_name)
        return Verdict(geometry_signature=signature_from_params(params, geometry_params=tuple(params.keys())),
                       fingerprint=fingerprint(), factor_of_safety=4.0, mesh_converged=True,
                       watertight=True, min_wall_ok=True, material=material_name, load_n=load_n,
                       solver_seconds=1.0)

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _fake_analyze_records_material)
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "domains.structure.material_profile", "requested_value": "ABS"})
        ws.receive_json()

    r = c.post("/analyze").json()
    assert r["status"] == "done"
    assert r["material"] == "ABS"    # THE pin: /analyze's own default, not a hardcoded "PLA"
    assert seen_material == ["ABS"]  # the fake solver was actually invoked with the real material

    c.post("/signoff", params={"reviewer": "pe@example.com"})
    # THE other pin: resolved_ledger() must look up the SAME "ABS"-keyed verdict just cached above, not
    # a hardcoded "PLA" one that was never solved — if it did, `derived` would stay unknown and this
    # would still read EXPORT_BLOCKED despite a real, passing, signed-off ABS verdict existing.
    assert c.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"


def test_optimize_also_uses_the_ledgers_real_material_not_a_hardcoded_pla(monkeypatch):
    # /optimize's sweep used to hardcode "PLA" in both its queued and inline solve calls, the same
    # class of bug as /analyze's — pin that the design's real material actually reaches the solver.
    seen_materials: list[str] = []

    def _fake_optimize(candidates, base_params, material_name, load_n, fs_floor, timeout_s,
                       subsystem_name="bracket", cut_features=None):
        seen_materials.append(material_name)
        best = candidates[0]
        v = Verdict(geometry_signature="x", fingerprint=fingerprint(), factor_of_safety=4.0,
                    mesh_converged=True, watertight=True, min_wall_ok=True,
                    material=material_name, load_n=load_n, solver_seconds=1.0)
        return {"variants": [{"value": c, "factor_of_safety": 4.0} for c in candidates],
                "best_value": best, "best_mass_g": 1.0, "best_verdict": v}

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "optimize_in_subprocess", _fake_optimize)
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "domains.structure.material_profile", "requested_value": "ABS"})
        ws.receive_json()

    r = c.post("/optimize").json()
    assert r["status"] == "done"
    assert seen_materials == ["ABS"]  # not the hardcoded "PLA" literal


# --- Defect 1 (2026-08-03): /analyze must not compute a real FS against a fabricated default load
# when the only thing on this part is a load-bearing coupling the force-only path can't consume ---

def test_analyze_refuses_to_compute_against_a_fabricated_load_when_only_a_moment_coupling_exists():
    # 'crank' carries a KNOWN, fully-resolved moment coupling — but nothing FORCE-shaped, no stated
    # goal, and no explicit load_n. Solving the real FS here would run against the hardcoded 40N
    # default, a number with no relationship to what this part actually carries.
    c = TestClient(create_app())
    crank = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    c.post("/coupling_ops", json={"op": "add_coupling", "target_instance": crank,
                                  "relation": "bending_from_distributed_load",
                                  "inputs": [{"name": "total_load_n", "value": 200.0},
                                             {"name": "span_mm", "value": 500.0}]})
    r = c.post("/analyze").json()
    assert r["status"] == "error"
    assert r.get("coupling_blocked") is True


def test_analyze_still_computes_when_the_caller_passes_load_n_explicitly():
    # an INFORMED override (an explicit load_n) must still be honored — the export gate independently
    # blocks regardless (packages.couplings.coupling_gate_findings), so this can never bypass real
    # enforcement, only this earlier, friendlier refusal.
    c = TestClient(create_app())
    crank = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    c.post("/coupling_ops", json={"op": "add_coupling", "target_instance": crank,
                                  "relation": "bending_from_distributed_load",
                                  "inputs": [{"name": "total_load_n", "value": 200.0},
                                             {"name": "span_mm", "value": 500.0}]})
    r = c.post("/analyze", params={"load_n": 40.0}).json()
    assert r.get("coupling_blocked") is not True
    assert r["status"] in ("done", "queued", "error")  # error here only for an unrelated reason (e.g. no solver)


def test_analyze_is_not_blocked_by_a_force_only_coupling():
    # do-not-over-block: a real, force-only coupling is exactly the case /analyze is SUPPOSED to solve
    # against — must never be refused.
    c = TestClient(create_app())
    crank = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    c.post("/coupling_ops", json={"op": "add_coupling", "target_instance": crank,
                                  "relation": "force_from_pressure_area",
                                  "inputs": [{"name": "pressure_pa", "value": 2e6},
                                             {"name": "area_mm2", "value": 500.0}]})
    r = c.post("/analyze").json()
    assert r.get("coupling_blocked") is not True
