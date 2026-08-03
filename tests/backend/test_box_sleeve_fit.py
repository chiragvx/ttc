"""box_sleeve <-> flat_bar (fitted-joint mechanism, Stage 1 rect-family proof) -- mirrors
tests/backend/test_fit_ops.py's round-family tests (spar_joiner_sleeve <-> round_post) and the
rotation-safety-gate style from tests/subsystems/test_fit.py::
test_compute_fit_refuses_a_non_square_rect_host, but against REAL registered subsystems for the
first time -- the round-family happy path already had a real end-to-end proof; the rect-family
rotation-safety gate up to now only had a synthetic one."""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.transport.app import create_app


def _client():
    return TestClient(create_app())


def _bar_and_sleeve(c, bar_id="bar1", sleeve_id="sleeve1"):
    bar = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "flat_bar",
                                        "instance_id": bar_id}).json()
    sleeve = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "box_sleeve",
                                           "instance_id": sleeve_id}).json()
    assert bar["status"] == "APPLIED" and sleeve["status"] == "APPLIED"
    return bar_id, sleeve_id


def test_fit_connector_derives_the_box_sleeves_bore_from_a_square_flat_bar_host():
    c = _client()
    bar_id, sleeve_id = _bar_and_sleeve(c)
    # flat_bar's fit_profile maps width_mm -> width_mm, thickness_mm -> height_mm (flat_bar.py) --
    # its own defaults (width_mm=20.0, thickness_mm=5.0) are NOT square, so square it up first.
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": f"instances.{bar_id}.params.thickness_mm", "requested_value": 20.0})
        ws.receive_json()
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id,
                                 "host_instance": bar_id, "clearance_mm": 0.6}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    assert r["binding"]["kind"] == "rect"
    assert sorted(r["binding"]["inputs"], key=lambda d: d["host_param"]) == [
        {"host_param": "height_mm", "connector_param": "bore_height_mm"},
        {"host_param": "width_mm", "connector_param": "bore_width_mm"},
    ]

    led = c.get("/ledger").json()
    # flat_bar's width_mm default is 20.0, thickness_mm now squared to 20.0 -> both bore dims
    # 20.0 + 0.6 clearance (deliberately != box_sleeve's own 20.4 default, so this value can only
    # mean "computed", never coincide with "still the untouched default")
    assert led["instances"][sleeve_id]["params"]["bore_width_mm"]["value"] == 20.6
    assert led["instances"][sleeve_id]["params"]["bore_height_mm"]["value"] == 20.6
    assert any(f["id"] == r["fit_id"] for f in led["fit_bindings"])


def test_fit_connector_refuses_a_non_square_flat_bar_host():
    # default flat_bar is width_mm=20.0, thickness_mm=5.0 -- NOT square -- the real rotation-safety
    # gate (packages/subsystems/fit.py::compute_fit), exercised here against real registered
    # subsystems for the first time (tests/subsystems/test_fit.py only covers it with synthetic ones).
    c = _client()
    bar_id, sleeve_id = _bar_and_sleeve(c)
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": sleeve_id,
                                 "host_instance": bar_id}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "not square" in r["message"]
    assert "rotation" in r["message"]
    led = c.get("/ledger").json()
    assert led["instances"][sleeve_id]["params"]["bore_width_mm"]["value"] == 20.4  # untouched default
    assert led["fit_bindings"] == []
