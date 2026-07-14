"""Empty-workspace genesis + multi-file design sessions (2026-07-04) — replaces the old
per-part-type switch_subsystem mechanic AND the single-project reset. A file starts with zero
instances; the first part added is just a plain top-level part (see
packages/ledger/apply.py::resolve_instance_parent) — never auto-parented, never treated as a
"root" everything else chains under. Multiple files can exist in one session (think browser
tabs); each has its own parts/goal/history, fully isolated. "Start completely over" is now
literally "open a new file" rather than a special reset endpoint."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

import packages.transport.app as app_module
from packages.ledger.gates import ExportStatus, GateResult
from packages.transport.app import create_app


def _client():
    return TestClient(create_app())


def test_subsystems_reports_no_active_part_initially():
    c = _client()
    body = c.get("/subsystems").json()
    assert body["active"] is None
    names = {s["name"] for s in body["available"]}
    assert {"bracket", "enclosure"} <= names


def test_adding_first_instance_becomes_the_active_subsystem():
    c = _client()
    r = c.post("/instances", json={"subsystem_type": "enclosure"}).json()
    iid = r["instance_id"]
    body = c.get("/subsystems").json()
    assert body["active"] == "enclosure"
    led = c.get("/ledger").json()
    assert "box_width_mm" in led["instances"][iid]["params"]
    assert led["instances"][iid]["params"]["box_width_mm"]["value"] == 80.0


def test_adding_first_instance_updates_telemetry_to_its_own_volume():
    c = _client()
    r = c.post("/instances", json={"subsystem_type": "enclosure"}).json()
    iid = r["instance_id"]
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": f"instances.{iid}.params.wall_thickness_mm", "requested_value": 3.0})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_CASCADE_UPDATE"
    assert msg["telemetry_delta"]["total_mass_g"] > 0


def test_unknown_subsystem_type_is_rejected():
    c = _client()
    res = c.post("/instances", json={"subsystem_type": "wing"}).json()
    assert res["ok"] is False
    assert "wing" in res["error"]


@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="needs build123d")
def test_export_step_follows_the_active_part(monkeypatch):
    # this test is about filename derivation from the active instance, not gate enforcement (covered
    # in tests/backend/test_app.py / test_analysis_api.py) — enclosure isn't fea_eligible, so its FS
    # can never resolve; stub the gate check eligible so the export itself is reached.
    monkeypatch.setattr(app_module, "evaluate_export_gates",
                        lambda *a, **k: GateResult(status=ExportStatus.EXPORT_ELIGIBLE, reasons=[], unknowns=[]))
    c = _client()
    c.post("/instances", json={"subsystem_type": "enclosure"})
    res = c.get("/export/step")
    assert res.status_code == 200
    assert "enclosure.step" in res.headers.get("content-disposition", "")


# --- multi-file (2026-07-04) -----------------------------------------------------------------------


def test_session_starts_with_one_untitled_file():
    c = _client()
    files = c.get("/files").json()["files"]
    assert len(files) == 1
    assert files[0]["name"] == "Untitled 1"
    assert files[0]["is_active"] is True
    assert files[0]["part_count"] == 0


def test_create_file_switches_to_it_and_starts_empty():
    c = _client()
    c.post("/instances", json={"subsystem_type": "bracket"})  # file 1 now has a part

    created = c.post("/files").json()
    assert created["ok"] is True
    assert created["name"] == "Untitled 2"

    # the new file is now active and empty
    assert c.get("/subsystems").json()["active"] is None
    assert c.get("/instances").json()["instances"] == []

    files = {f["id"]: f for f in c.get("/files").json()["files"]}
    assert len(files) == 2
    assert files[created["id"]]["is_active"] is True
    assert files[created["id"]]["part_count"] == 0


def test_files_are_fully_isolated():
    c = _client()
    file1 = c.get("/files").json()["files"][0]["id"]
    c.post("/instances", json={"subsystem_type": "bracket"})
    c.post("/requirements", json={"goal": "hold the load at FS 3"})

    file2 = c.post("/files").json()["id"]
    # file 2 sees none of file 1's parts or goal
    assert c.get("/instances").json()["instances"] == []
    assert c.get("/requirements").json()["goal_set"] is False

    c.post(f"/files/{file1}/open")
    # switching back to file 1 restores its parts and goal
    rows = c.get("/instances").json()["instances"]
    assert len(rows) == 1 and rows[0]["subsystem_type"] == "bracket"
    assert c.get("/requirements").json()["goal_set"] is True

    c.post(f"/files/{file2}/open")
    assert c.get("/instances").json()["instances"] == []


def test_open_unknown_file_is_rejected():
    c = _client()
    res = c.post("/files/does-not-exist/open").json()
    assert res["ok"] is False
