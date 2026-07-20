"""Phase 1b (2026-07-19) — ConnectionOp: the copilot MATES parts via typed interfaces instead of
hand-computing positions. apply_connection_op + /connection_ops + event-sourced persistence + the
prompt teaching interfaces/connection_ops."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from packages.transport.app import create_app

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _client():
    return TestClient(create_app())


def _bwb_and_wing(c):
    body = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bwb_fuselage"}).json()["instance_id"]
    wr = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel"}).json()["instance_id"]
    return body, wr


def test_add_connection_works_for_the_generic_bar_end_interfaces_too():
    # 2026-07-20 — proves the whole REST stack (not just the pure solver) accepts the new
    # bar_end_interfaces()-declared interfaces, not just the original hand-authored bwb_fuselage/
    # wing_panel pair.
    c = _client()
    la = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "longeron"}).json()["instance_id"]
    lb = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "longeron"}).json()["instance_id"]
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": la, "a_interface": "end_b",
                                        "b_instance": lb, "b_interface": "end_a"}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert any(conn["id"] == r["connection_id"] for conn in led["connections"])


def test_add_connection_applies_and_persists_through_replay():
    c = _client()
    body, wr = _bwb_and_wing(c)
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                        "b_instance": body, "b_interface": "tip_right"}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    cid = r["connection_id"]
    # persisted through the event log -> a fresh ledger read still has it
    led = c.get("/ledger").json()
    assert any(conn["id"] == cid for conn in led["connections"])


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_connection_places_the_wing_at_the_body_tip():
    c = _client()
    body, wr = _bwb_and_wing(c)
    # before connecting, the wing is auto-laid-out (off to +Y), not on the tip
    c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                    "b_instance": body, "b_interface": "tip_right"})
    rows = {i["id"]: i for i in c.get("/instances").json()["instances"]}
    wx, wy, wz = rows[wr]["world_offset"]
    # body default span 800 -> tip at x=400; the mate must place the wing root there (not near 0/auto)
    assert wx == pytest.approx(400.0, abs=1.0)


def test_hallucinated_interface_is_rejected():
    c = _client()
    body, wr = _bwb_and_wing(c)
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "ghost",
                                        "b_instance": body, "b_interface": "tip_right"}).json()
    assert r["status"] == "REJECTED"
    assert "no interface 'ghost'" in r["message"]


def test_self_connection_is_rejected():
    c = _client()
    body, _ = _bwb_and_wing(c)
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": body, "a_interface": "tip_right",
                                        "b_instance": body, "b_interface": "tip_left"}).json()
    assert r["status"] == "REJECTED"
    assert "itself" in r["message"]


def test_remove_connection():
    c = _client()
    body, wr = _bwb_and_wing(c)
    cid = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                          "b_instance": body, "b_interface": "tip_right"}).json()["connection_id"]
    r = c.post("/connection_ops", json={"op": "remove_connection", "id": cid}).json()
    assert r["ok"]
    assert c.get("/ledger").json()["connections"] == []


def test_removing_an_instance_cascade_removes_its_connections_and_survives_replay():
    # 2026-07-19 review (MEDIUM): a dangling connection whose part was removed would silently
    # resurrect onto an id-reused new part (wrong geometry + false 'joined'). Removing an instance
    # must cascade-remove its connections, persisted so replay reproduces the cascade — no resurrection.
    c = _client()
    body, wr = _bwb_and_wing(c)
    c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                    "b_instance": body, "b_interface": "tip_right"})
    assert len(c.get("/ledger").json()["connections"]) == 1
    c.post("/instance_ops", json={"op": "remove_instance", "instance_id": wr})
    assert c.get("/ledger").json()["connections"] == []          # cascade-removed (and via replay)
    # re-adding the same type reuses the id — the stale connection must NOT come back
    wr2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel"}).json()["instance_id"]
    assert wr2 == wr  # id reuse (lowest-free)
    assert c.get("/ledger").json()["connections"] == []


def test_prompt_teaches_interfaces_and_connection_ops():
    from packages.agents.prompt_builder import build_system_prompt
    from packages.transport.app import make_demo_ledger
    prompt = build_system_prompt(None, make_demo_ledger())
    # the interfaces are listed in the part-types menu
    assert "tip_left" in prompt and "tip_right" in prompt and "mate points" in prompt
    # and the connection_ops capability is taught
    assert "connection_ops" in prompt and "add_connection" in prompt
