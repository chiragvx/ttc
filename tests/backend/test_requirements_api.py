"""The goal-grounded design loop: a stated goal -> a verification matrix, judged against LIVE metrics.

The keystone is the grounding: factor_of_safety in the compliance readout comes from a real solver
verdict, so it is UNKNOWN (never assumed satisfied) until an analysis has run for the current geometry
— mass / print-time are deterministic geometry and are known immediately.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import packages.transport.app as app_module
from packages.ledger.derived_resolver import Verdict, signature_from_params
from packages.ledger.fingerprint import fingerprint


def _fake_analyze(params, material_name, load_n):
    return Verdict(geometry_signature=signature_from_params(params), fingerprint=fingerprint(),
                   factor_of_safety=2.4, mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=2.5)


def _client(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _fake_analyze)
    return TestClient(app_module.create_app())


def test_no_goal_is_empty(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/requirements").json()
    assert r["goal_set"] is False and r["total"] == 0 and r["requirements"] == []


def test_goal_parses_to_targets_and_implies_fs_floor(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/requirements", json={"goal": "a bracket that holds 200 N at FS 2 and stays under 30 g"}).json()
    assert r["goal_set"] is True
    by_metric = {req["metric"]: req for req in r["requirements"]}
    assert by_metric["factor_of_safety"]["op"] == ">=" and by_metric["factor_of_safety"]["target"] == 2.0
    assert by_metric["mass_g"]["op"] == "<=" and by_metric["mass_g"]["target"] == 30.0
    assert r["implied_fs_floor"] == 2.0   # the strictest stated FS -> the floor the goal demands


def test_fs_unknown_until_analyzed_then_grounded(monkeypatch):
    c = _client(monkeypatch)
    c.post("/requirements", json={"goal": "hold the load at FS 2, under 30 g"})

    before = {req["metric"]: req for req in c.get("/requirements").json()["requirements"]}
    assert before["factor_of_safety"]["status"] == "UNKNOWN"     # no verdict yet -> never assumed
    assert before["factor_of_safety"]["value"] is None
    # mass is deterministic geometry -> KNOWN immediately (pass or fail), never UNKNOWN
    assert before["mass_g"]["status"] in ("SATISFIED", "VIOLATED")
    assert before["mass_g"]["value"] is not None

    c.post("/analyze")                                          # real-shaped verdict (faked FS 2.4)
    after = {req["metric"]: req for req in c.get("/requirements").json()["requirements"]}
    assert after["factor_of_safety"]["status"] == "SATISFIED"    # 2.4 >= 2.0, grounded in the verdict
    assert after["factor_of_safety"]["value"] == 2.4


def test_violated_fs_goal_is_reported_not_hidden(monkeypatch):
    c = _client(monkeypatch)
    c.post("/requirements", json={"goal": "hold the load at FS 3"})  # stricter than the faked 2.4
    c.post("/analyze")
    fs = {req["metric"]: req for req in c.get("/requirements").json()["requirements"]}["factor_of_safety"]
    assert fs["status"] == "VIOLATED" and fs["value"] == 2.4
