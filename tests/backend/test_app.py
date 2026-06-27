"""FastAPI app: REST + the two-plane WebSocket (cascade + NACK paths)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.transport.app import create_app

SKIN = "domains.structure.skin_thickness_mm"


def _client():
    return TestClient(create_app())


def test_healthz_and_initial_ledger():
    c = _client()
    assert c.get("/healthz").json() == {"ok": True}
    led = c.get("/ledger").json()
    assert led["domains"]["structure"]["skin_thickness_mm"]["value"] == 2.0


def test_ws_valid_mutation_returns_cascade_and_persists():
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 3.0})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_CASCADE_UPDATE"
    assert msg["mutations_applied"][0] == {"node": SKIN, "value": 3.0, "status": "APPLIED"}
    assert msg["telemetry_delta"]["total_mass_g"] > 0
    # committed to the shared event log
    assert c.get("/ledger").json()["domains"]["structure"]["skin_thickness_mm"]["value"] == 3.0


def test_ws_out_of_bounds_is_clamped():
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 9.0})
        msg = ws.receive_json()
    assert msg["mutations_applied"][0]["status"] == "CLAMPED"
    assert msg["mutations_applied"][0]["value"] == 5.0


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


def test_export_check_blocks_on_unknown_safety():
    c = _client()
    res = c.post("/export/check").json()
    assert res["status"] == "EXPORT_BLOCKED"
    assert "factor_of_safety" in res["unknowns"]
