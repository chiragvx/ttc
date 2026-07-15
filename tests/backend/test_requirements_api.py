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


def _fake_analyze(params, material_name, load_n, subsystem_name="bracket", cut_features=None):
    return Verdict(geometry_signature=signature_from_params(params, geometry_params=tuple(params.keys())),
                   fingerprint=fingerprint(),
                   factor_of_safety=2.4, mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=2.5)


def _client(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _fake_analyze)
    # a project starts as an empty workspace (2026-07-04) — bootstrap the bracket root every other
    # test here relies on, exactly as genesis used to seed it automatically.
    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    return c


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


def test_goal_raises_the_enforced_export_floor(monkeypatch):
    # the stated FS target must be ENFORCED at the gate, not merely reported. The LLM sets the target;
    # the deterministic gate enforces it.
    c = _client(monkeypatch)
    c.post("/analyze")                                              # FS 2.4 (faked)
    c.post("/signoff", params={"reviewer": "pe@example.com"})
    assert c.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"  # default floor 1.5 -> passes

    c.post("/requirements", json={"goal": "hold the load at FS 3"})  # now demand FS >= 3
    r = c.post("/export/check").json()
    assert r["status"] == "EXPORT_BLOCKED"                          # the SAME design is now blocked
    assert any("below floor 3" in reason for reason in r["reasons"])


def test_goal_load_is_implied_but_not_a_requirement_row(monkeypatch):
    # 2026-07-15: a stated load surfaces as implied_load_n (a solver INPUT the UI can show), but never
    # as one of the checkable "requirements" rows -- there is no metric to solve/report it against.
    c = _client(monkeypatch)
    r = c.post("/requirements", json={"goal": "a bracket that holds 200 N at FS 2"}).json()
    assert r["implied_load_n"] == 200.0
    assert "load_n" not in {req["metric"] for req in r["requirements"]}


def test_no_goal_implies_no_load(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/requirements").json()["implied_load_n"] is None


def test_optimize_targets_the_goal_floor(monkeypatch):
    # "Find a passing design" must aim at the STATED goal, not the default 1.5 floor
    captured: dict = {}

    def _capture(candidates, base_params, material_name, load_n, fs_floor, timeout_s=600.0,
                subsystem_name="bracket", cut_features=None):
        captured["floor"] = fs_floor
        return {"variants": [], "best_value": None, "best_mass_g": None, "best_verdict": None,
               "param_name": "skin_thickness_mm"}

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "optimize_in_subprocess", _capture)
    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    c.post("/requirements", json={"goal": "hold the load at FS 3"})
    c.post("/optimize")
    assert captured["floor"] == 3.0   # the goal raised the sweep's target floor


def test_analyze_resolves_load_n_from_the_stated_goal(monkeypatch):
    # 2026-07-15 fix: the stated load must actually reach the solver -- before this, /analyze always
    # solved a hardcoded 40 N tip load no matter what the goal asked for, so the reported FS was real
    # but for the WRONG load case.
    captured: dict = {}

    def _capture(params, material_name, load_n, subsystem_name="bracket", cut_features=None):
        captured["load_n"] = load_n
        return Verdict(geometry_signature=signature_from_params(params, geometry_params=tuple(params.keys())),
                       fingerprint=fingerprint(), factor_of_safety=4.0, mesh_converged=True,
                       watertight=True, min_wall_ok=True, solver_seconds=2.5)

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _capture)
    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})

    c.post("/requirements", json={"goal": "a bracket that holds 200 N at FS 2"})
    r = c.post("/analyze").json()
    assert captured["load_n"] == 200.0   # not the historical hardcoded 40 N default
    assert r["load_n"] == 200.0          # echoed back so a poller can ask about the SAME case


def test_optimize_resolves_load_n_from_the_stated_goal(monkeypatch):
    captured: dict = {}

    def _capture(candidates, base_params, material_name, load_n, fs_floor, timeout_s=600.0,
                subsystem_name="bracket", cut_features=None):
        captured["load_n"] = load_n
        return {"variants": [], "best_value": None, "best_mass_g": None, "best_verdict": None,
               "param_name": "skin_thickness_mm"}

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "optimize_in_subprocess", _capture)
    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    c.post("/requirements", json={"goal": "a bracket that holds 150 N"})
    c.post("/optimize")
    assert captured["load_n"] == 150.0   # not the historical hardcoded 25 N default
