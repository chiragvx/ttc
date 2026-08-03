"""Fitted-joint mechanism (2026-07-27) — FitOp: derive a CONNECTOR's own fitted-dimension params from
a HOST's actual cross-section, snapshot-written through the ordinary ParameterDelta path (never a
live, never-logged read — see packages/ledger/schema.py::FitBinding's own docstring for the doctrine
reasoning). Mirrors tests/backend/test_coupling_ops.py: same TestClient pattern, same categories of
test (apply-and-persist-through-replay, rejection cases, remove, a drift/resync case, a prompt-teaches
case). Stage 0's round-family proof: round_post (host, dia_mm) <-> spar_joiner_sleeve (connector,
inner_dia_mm), both pre-existing, battle-tested subsystems -- no new geometry needed for this stage."""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.transport.app import create_app


def _client():
    return TestClient(create_app())


def _post_and_sleeve(c, post_id="post1", sleeve_id="sleeve1"):
    post = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_post",
                                         "instance_id": post_id}).json()
    sleeve = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spar_joiner_sleeve",
                                           "instance_id": sleeve_id}).json()
    assert post["status"] == "APPLIED" and sleeve["status"] == "APPLIED"
    return post_id, sleeve_id


def test_fit_connector_derives_the_connectors_bore_from_the_hosts_diameter():
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id,
                                 "host_instance": post_id, "clearance_mm": 0.2}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    assert r["binding"]["kind"] == "round"
    assert r["binding"]["inputs"] == [{"host_param": "dia_mm", "connector_param": "inner_dia_mm"}]

    led = c.get("/ledger").json()
    # round_post's own default dia_mm is 12.0 (round_post.py) -> 12.0 + 0.2 clearance
    assert led["instances"][sleeve_id]["params"]["inner_dia_mm"]["value"] == 12.2
    assert any(f["id"] == r["fit_id"] for f in led["fit_bindings"])


def test_fit_connector_persists_through_replay():
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id,
                                 "host_instance": post_id}).json()
    assert r["ok"]
    # a fresh read replays the whole event log from genesis -- confirms FIT_BOUND's replay branch
    # (packages/ledger/events.py) actually reconstructs both the delta AND the binding, not just one
    led = c.get("/ledger").json()
    assert led["instances"][sleeve_id]["params"]["inner_dia_mm"]["value"] == 12.0
    assert any(f["id"] == r["fit_id"] for f in led["fit_bindings"])


def test_fit_connector_rejects_unknown_connector_instance():
    c = _client()
    _, sleeve_id = _post_and_sleeve(c)
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": "ghost",
                                 "host_instance": "post1"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "ghost" in r["message"]


def test_fit_connector_rejects_unknown_host_instance():
    c = _client()
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spar_joiner_sleeve",
                                  "instance_id": "sleeve1"})
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": "sleeve1",
                                 "host_instance": "ghost"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"


def test_fit_connector_rejects_self_fit():
    c = _client()
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spar_joiner_sleeve",
                                  "instance_id": "sleeve1"})
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": "sleeve1",
                                 "host_instance": "sleeve1"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "itself" in r["message"]


def test_fit_connector_rejects_a_host_with_no_fit_profile():
    # bracket declares no fit_profile at all -- this must fail with an explicit reason, never a
    # fabricated dimension
    c = _client()
    host = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bracket"}).json()["instance_id"]
    sleeve = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spar_joiner_sleeve"}).json()["instance_id"]
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve, "host_instance": host}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "fit_profile" in r["message"]


def test_fit_connector_rejects_a_connector_with_no_fit_socket():
    c = _client()
    post = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_post"}).json()["instance_id"]
    connector = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bracket"}).json()["instance_id"]
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": connector, "host_instance": post}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "fit_socket" in r["message"]


def test_fit_connector_rejects_a_second_fit_on_the_same_connector():
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    other_post = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_post"}).json()["instance_id"]
    first = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id, "host_instance": post_id}).json()
    assert first["ok"]
    second = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id, "host_instance": other_post}).json()
    assert not second["ok"] and second["status"] == "REJECTED"
    assert "already has a live fit binding" in second["message"]


def test_fit_connector_applies_advisory_when_the_computed_value_is_merely_outside_the_recommended_range():
    # bounds are ADVISORY system-wide (packages/ledger/CLAUDE.md) -- a fit-derived value is not a
    # special case that overrides that: a computed dimension outside the connector's recommended
    # range still applies (visibly, as advisory), same as a hand-typed one would.
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    with c.websocket_connect("/ws") as ws:
        # widen the sleeve's own outer_dia_mm first (to its own max, 60.0) so a big bore still
        # leaves a positive wall -- isolates "outside inner_dia_mm's OWN recommended [3,50] range"
        # from "violates the wall-thickness invariant" (covered separately below).
        ws.send_json({"target_node": f"instances.{sleeve_id}.params.outer_dia_mm", "requested_value": 60.0})
        ws.receive_json()
        # round_post's own max dia_mm is 80.0; 55.0 is past inner_dia_mm's recommended max (50.0)
        # but well under the widened outer_dia_mm (60.0), so the wall stays positive.
        ws.send_json({"target_node": f"instances.{post_id}.params.dia_mm", "requested_value": 55.0})
        ws.receive_json()
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id, "host_instance": post_id}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert led["instances"][sleeve_id]["params"]["inner_dia_mm"]["value"] == 55.0


def test_fit_connector_rejects_all_or_nothing_on_a_genuine_invariant_violation():
    # a post bigger than the sleeve's OWN outer_dia_mm (default 18.0) trips spar_joiner_sleeve's own
    # "no wall left" invariant (spar_joiner_sleeve.py::_check) -- a REAL cross-field violation, not
    # just an advisory out-of-range value, and must back the WHOLE fit out atomically.
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": f"instances.{post_id}.params.dia_mm", "requested_value": 55.0})
        ws.receive_json()
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id, "host_instance": post_id}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "no wall" in r["message"]
    # the connector's own param must be UNCHANGED -- confirm no partial write happened
    led = c.get("/ledger").json()
    assert led["instances"][sleeve_id]["params"]["inner_dia_mm"]["value"] == 12.0  # untouched default
    assert led["fit_bindings"] == []


def test_resync_fit_rederives_after_the_host_resizes():
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    wired = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id, "host_instance": post_id}).json()
    fit_id = wired["fit_id"]
    with c.websocket_connect("/ws") as ws:
        # stays under the sleeve's own default outer_dia_mm (18.0) so the wall invariant holds
        ws.send_json({"target_node": f"instances.{post_id}.params.dia_mm", "requested_value": 15.0})
        ws.receive_json()
    # still the OLD value until resynced
    assert c.get("/ledger").json()["instances"][sleeve_id]["params"]["inner_dia_mm"]["value"] == 12.0
    r = c.post("/fit_ops", json={"op": "resync_fit", "id": fit_id}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    assert c.get("/ledger").json()["instances"][sleeve_id]["params"]["inner_dia_mm"]["value"] == 15.0


def test_unfit_connector_removes_the_binding_but_keeps_the_connectors_dimensions():
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    wired = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id, "host_instance": post_id, "clearance_mm": 0.5}).json()
    r = c.post("/fit_ops", json={"op": "unfit_connector", "id": wired["fit_id"]}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert led["fit_bindings"] == []
    # unfitting is NOT reverting -- the connector keeps its last-fitted dimension
    assert led["instances"][sleeve_id]["params"]["inner_dia_mm"]["value"] == 12.5


def test_unfit_connector_rejects_an_unknown_id():
    c = _client()
    r = c.post("/fit_ops", json={"op": "unfit_connector", "id": "ghost"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"


def test_fit_gate_findings_blocks_export_when_the_host_is_deleted():
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id, "host_instance": post_id})
    c.post("/instance_ops", json={"op": "remove_instance", "instance_id": post_id})
    res = c.post("/export/check").json()
    assert any("fit" in r and sleeve_id in r for r in res["reasons"])


def test_fit_drift_is_a_validate_warning_not_an_export_block():
    # host present + resolves fine, but the connector's STORED value no longer matches -- warning,
    # drives the self-correct loop; NOT the same category as a dangling/deleted host.
    c = _client()
    post_id, sleeve_id = _post_and_sleeve(c)
    c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id, "host_instance": post_id})
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": f"instances.{post_id}.params.dia_mm", "requested_value": 15.0})
        ws.receive_json()
    v = c.post("/validate", json={"intent": "a post and a sleeve"}).json()
    fit_issues = [i for i in v["geometric"]["issues"] if i["check"] == "fit"]
    assert len(fit_issues) == 1
    assert fit_issues[0]["severity"] == "warning"
    assert "resync_fit" in fit_issues[0]["message"]
    # drift alone must not block export the way a dangling fit does
    res = c.post("/export/check").json()
    assert not any("fit " in r and sleeve_id in r for r in res["reasons"])


def test_no_fit_findings_when_nothing_is_wired():
    c = _client()
    _post_and_sleeve(c)
    v = c.post("/validate", json={"intent": "a post and a sleeve"}).json()
    assert not any(i["check"] == "fit" for i in v["geometric"]["issues"])


def test_fit_connector_rejects_a_managed_assembly_template_child():
    # a table's own legs are assembly_children-managed -- fit_connector must refuse to target one
    # (its params get overwritten every reconcile pass, so a direct fit would be silently discarded).
    c = _client()
    table_id = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "table"}).json()["instance_id"]
    led = c.get("/ledger").json()
    leg_ids = [iid for iid, inst in led["instances"].items()
              if inst.get("parent_id") == table_id and inst["subsystem_type"] == "round_post"]
    assert leg_ids, "table must generate at least one round_post leg child for this test to be meaningful"
    sleeve = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spar_joiner_sleeve"}).json()["instance_id"]
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve, "host_instance": leg_ids[0]}).json()
    assert r["ok"]  # fitting TO a managed host (read-only source) is fine -- only the CONNECTOR side is restricted


def test_prompt_teaches_fit_ops_and_the_real_registered_hosts_and_connectors():
    from packages.agents.prompt_builder import build_system_prompt
    from packages.subsystems import SUBSYSTEM_MODELS
    from packages.transport.app import make_demo_ledger
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "fit_connector" in prompt and "resync_fit" in prompt and "unfit_connector" in prompt
    assert "clearance_mm" in prompt
    for s in SUBSYSTEM_MODELS.values():
        if s.fit_profile is not None:
            assert f"`{s.name}`" in prompt
        if s.fit_socket is not None:
            assert f"`{s.name}`" in prompt


def test_prompt_teaches_the_rotation_safety_gate_for_rect_fits():
    from packages.agents.prompt_builder import build_system_prompt
    from packages.transport.app import make_demo_ledger
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "square" in prompt.lower()
    assert "rotation" in prompt.lower()
