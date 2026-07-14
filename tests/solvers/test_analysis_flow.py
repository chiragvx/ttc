"""Phase 4 e2e (container): analyze -> sign-off flips the export gate; a geometry change makes it stale."""

from __future__ import annotations

import importlib.util
import shutil

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.needs_kernel, pytest.mark.needs_solver]

_HAS = importlib.util.find_spec("build123d") is not None and shutil.which("ccx") is not None
SKIN = "instances.root.params.skin_thickness_mm"


@pytest.fixture
def client():
    if not _HAS:
        pytest.skip("needs build123d + ccx (Linux container)")
    from packages.transport.app import create_app
    return TestClient(create_app())


def test_analyze_geometry_returns_grounded_verdict():
    if not _HAS:
        pytest.skip("needs build123d + ccx")
    from packages.ledger.nodes import RIB, SKIN as SK
    from packages.truth_plane.analysis import analyze_geometry
    v = analyze_geometry({SK: 8.0, RIB: 20.0}, "PLA", 40.0)
    assert v.factor_of_safety and v.factor_of_safety > 1.5
    assert v.mesh_converged and v.watertight and v.min_wall_ok
    assert v.solver_seconds > 0 and len(v.geometry_signature) == 64


def test_export_gate_flips_then_goes_stale(client):
    assert client.post("/export/check").json()["status"] == "EXPORT_BLOCKED"

    # the default 2 mm plate genuinely fails FS — thicken it to 8 mm first (as a user would)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 8.0})
        ws.receive_json()

    r = client.post("/analyze", params={"load_n": 40.0}).json()
    assert r["status"] == "done" and r["verdict"]["factor_of_safety"] > 1.5

    # FS exists but no sign-off yet -> still blocked
    assert client.post("/export/check").json()["status"] == "EXPORT_BLOCKED"

    client.post("/signoff", params={"reviewer": "pe@example.com"})
    assert client.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"

    # cached verdict is reused (no re-run)
    assert client.post("/analyze").json().get("cached") is True

    # change geometry -> the verdict no longer matches -> stale -> blocked
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 3.0})
        ws.receive_json()
    assert client.post("/export/check").json()["status"] == "EXPORT_BLOCKED"

    # neutral STEP export works
    assert client.get("/export/step").status_code == 200
