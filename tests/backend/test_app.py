"""FastAPI app: REST + the two-plane WebSocket (cascade + NACK paths)."""

from __future__ import annotations

import importlib.util
import time

import pytest
from fastapi.testclient import TestClient

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

    def fake_stream_chat(self, *, messages, ledger_json):
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

    def fake_stream_chat(self, *, messages, ledger_json):
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
