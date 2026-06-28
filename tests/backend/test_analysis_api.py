"""Phase 4 loop on Windows (solver faked; build123d export is real): analyze -> sign-off -> flip -> stale."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

import packages.transport.app as app_module
from packages.ledger.derived_resolver import Verdict, signature_from_params
from packages.ledger.fingerprint import fingerprint
from packages.ledger.nodes import SKIN

_HAS_KERNEL = importlib.util.find_spec("build123d") is not None


def _fake_analyze(params, material_name, load_n):
    return Verdict(geometry_signature=signature_from_params(params), fingerprint=fingerprint(),
                   factor_of_safety=4.0, mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=2.5)


def _client(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _fake_analyze)
    return TestClient(app_module.create_app())


def test_analysis_flips_export_gate_then_goes_stale(monkeypatch):
    c = _client(monkeypatch)
    assert c.post("/export/check").json()["status"] == "EXPORT_BLOCKED"

    r = c.post("/analyze").json()
    assert r["status"] == "done" and r["verdict"]["factor_of_safety"] == 4.0

    assert c.post("/export/check").json()["status"] == "EXPORT_BLOCKED"   # FS present, no sign-off yet
    c.post("/signoff", params={"reviewer": "pe@example.com"})
    assert c.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"  # flips

    assert c.post("/analyze").json().get("cached") is True               # idempotent (no re-run)

    with c.websocket_connect("/ws") as ws:                               # change geometry -> stale
        ws.send_json({"target_node": SKIN, "requested_value": 3.0})
        ws.receive_json()
    assert c.post("/export/check").json()["status"] == "EXPORT_BLOCKED"

    # re-analyze the new geometry + sign off -> eligible again
    c.post("/analyze")
    c.post("/signoff")
    assert c.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"


def test_analyze_status_reflects_current_geometry(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/analyze/status").json()["current"] is None
    c.post("/analyze")
    assert c.get("/analyze/status").json()["current"]["factor_of_safety"] == 4.0


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d for STEP export")
def test_export_step_streams_real_brep(monkeypatch):
    c = _client(monkeypatch)
    resp = c.get("/export/step")
    assert resp.status_code == 200
    assert resp.content[:13].decode("ascii", "ignore").startswith("ISO-10303-21")
