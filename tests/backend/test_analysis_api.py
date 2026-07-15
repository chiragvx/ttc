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


def _fake_analyze(params, material_name, load_n, subsystem_name="bracket", cut_features=None):
    return Verdict(geometry_signature=signature_from_params(params, geometry_params=tuple(params.keys())),
                   fingerprint=fingerprint(),
                   factor_of_safety=4.0, mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=2.5)


def _client(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _fake_analyze)
    # a project starts as an empty workspace (2026-07-04) — bootstrap the bracket root every other
    # test here relies on, exactly as genesis used to seed it automatically.
    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    return c


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


def test_moving_an_instance_after_signoff_reblocks_export_via_review_reset(monkeypatch):
    """Isolates the review-reset fix from FS staleness: repositioning an instance (Transform only)
    does NOT touch any geometry param the FS signature hashes, so the cached verdict stays fresh --
    yet export must still re-block, because the human sign-off itself no longer covers this design
    (schema.py's Review docstring: 'Geometry-class changes start AI_PROPOSED'). Before this fix,
    review never reset on its own and this would have stayed EXPORT_ELIGIBLE."""
    c = _client(monkeypatch)
    c.post("/analyze")
    c.post("/signoff", params={"reviewer": "pe@example.com"})
    assert c.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"

    root_id = c.get("/ledger").json()["root_id"]
    move = c.post("/instance_ops", json={
        "op": "move_instance", "instance_id": root_id, "x_mm": 10.0, "y_mm": 0.0, "z_mm": 0.0,
    }).json()
    assert move["ok"] is True

    assert c.post("/analyze").json().get("cached") is True  # FS verdict is still fresh, unaffected
    assert c.post("/export/check").json()["status"] == "EXPORT_BLOCKED"  # but review reset -> blocked


def test_analyze_status_reflects_current_geometry(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/analyze/status").json()["current"] is None
    c.post("/analyze")
    assert c.get("/analyze/status").json()["current"]["factor_of_safety"] == 4.0


def test_queued_analyze_records_status_durably_across_the_process_boundary(monkeypatch):
    """2026-07-15 fix: before this, a queued job's status lived only in a `publish` callback that
    could never reach the web process from the separate worker process — a poller had no way to
    tell 'still running' apart from 'crashed with no signal at all'. The web process now writes
    'queued' itself right after enqueueing (verified here); packages/backend/test_jobs.py verifies
    the worker side writes 'running'/'done'/'failed' onto the SAME durable store."""
    # import BEFORE setting REDIS_URL: jobs.py picks its broker (Redis vs Stub) ONCE at import time,
    # from whatever REDIS_URL was set to then — importing first guarantees a StubBroker (no real
    # `redis` package needed) regardless of which order pytest happens to collect test files in.
    import packages.truth_plane.jobs as jobs_module
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://fake/0")  # makes the ROUTE take the queued branch
    monkeypatch.setattr(jobs_module.run_fs_analysis, "send", lambda *a, **k: None)  # don't actually enqueue

    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})

    assert c.get("/analyze/status").json()["job_status"] is None  # nothing queued yet

    r = c.post("/analyze").json()
    assert r["status"] == "queued"

    status = c.get("/analyze/status").json()
    assert status["current"] is None       # no verdict yet -- the job hasn't actually run
    assert status["job_status"] == "queued"  # but the poller can tell it WAS accepted, not lost


def test_analyze_status_surfaces_a_failed_queued_job(monkeypatch):
    """Simulates what the worker process would have durably recorded on a crash -- writes directly
    to the SAME status_store the web process reads, exactly like a real worker (a separate process)
    would via the shared Postgres table in compose."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _fake_analyze)
    app = app_module.create_app()
    c = TestClient(app)
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})

    session = app.state.sessions.only()
    session.status_store.put_status(session.project_id, "failed", message="solver exploded")

    status = c.get("/analyze/status").json()
    assert status["job_status"] == "failed"
    assert status["job_message"] == "solver exploded"


def _fake_optimize(candidates, base_params, material_name, load_n, fs_floor, timeout_s=600.0,
                   subsystem_name="bracket", cut_features=None):
    merged = {**base_params, SKIN: 4.0}
    verdict = Verdict(geometry_signature=signature_from_params(merged, geometry_params=tuple(merged.keys())),
                      fingerprint=fingerprint(),
                      factor_of_safety=1.8, mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=12.0)
    return {
        "variants": [
            {"value": 2.0, "fs": 0.4, "mass_g": 59.0, "feasible": False},
            {"value": 3.0, "fs": 0.9, "mass_g": 89.0, "feasible": False},
            {"value": 4.0, "fs": 1.8, "mass_g": 119.0, "feasible": True},
            {"value": 5.0, "fs": 2.8, "mass_g": 149.0, "feasible": True},
        ],
        "best_value": 4.0, "best_mass_g": 119.0, "best_verdict": verdict, "param_name": "skin_thickness_mm",
    }


def test_optimize_picks_lightest_feasible_applies_and_flips(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(app_module, "optimize_in_subprocess", _fake_optimize)
    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})

    r = c.post("/optimize").json()
    assert r["status"] == "done" and r["best_value"] == 4.0  # lightest passing (not the heaviest 5.0)
    assert r["param_name"] == "skin_thickness_mm"
    assert [v["feasible"] for v in r["variants"]] == [False, False, True, True]

    # the chosen design is applied to the ledger
    assert c.get("/ledger").json()['instances']['root']['params']["skin_thickness_mm"]["value"] == 4.0
    # and its verdict flips the gate after sign-off
    c.post("/signoff")
    assert c.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"


def test_optimize_unsupported_for_non_eligible_active_subsystem(monkeypatch):
    """A cylindrical/rotational part (or any subsystem without a fea_eligible thickness param) gets
    an honest 'unsupported' from /optimize instead of a wrong or no-op sweep."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "root"})
    r = c.post("/optimize").json()
    assert r["status"] == "unsupported"


def test_optimize_works_for_a_newly_eligible_non_bracket_subsystem(monkeypatch):
    """Generalized (2026-07-03): optimize discovers and sweeps ANY fea_eligible subsystem's own
    thickness param, not just bracket's skin_thickness_mm."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def _fake_flat_bar_optimize(candidates, base_params, material_name, load_n, fs_floor,
                                timeout_s=600.0, subsystem_name="bracket", cut_features=None):
        assert subsystem_name == "flat_bar"
        return {"variants": [{"value": c, "fs": 3.0, "mass_g": 10.0, "feasible": True} for c in candidates],
               "best_value": candidates[0], "best_mass_g": 10.0, "best_verdict": None,
               "param_name": "thickness_mm"}

    monkeypatch.setattr(app_module, "optimize_in_subprocess", _fake_flat_bar_optimize)
    c = TestClient(app_module.create_app())
    c.post("/instances", json={"subsystem_type": "flat_bar", "instance_id": "root"})
    r = c.post("/optimize").json()
    assert r["status"] == "done"
    assert r["param_name"] == "thickness_mm"
    assert r["target_node"] == "instances.root.params.thickness_mm"
    # the chosen value was applied to the ledger via the RIGHT dotted path
    assert c.get("/ledger").json()["instances"]["root"]["params"]["thickness_mm"]["value"] == r["best_value"]


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d for STEP export")
def test_export_step_streams_real_brep(monkeypatch):
    c = _client(monkeypatch)
    # gates are now enforced server-side at the export endpoint itself — must actually analyze +
    # sign off first, the same sequence the frontend's voluntary check-then-export used to be the
    # ONLY thing enforcing.
    c.post("/analyze")
    c.post("/signoff", params={"reviewer": "pe@example.com"})
    resp = c.get("/export/step")
    assert resp.status_code == 200
    assert resp.content[:13].decode("ascii", "ignore").startswith("ISO-10303-21")


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d for STEP export")
def test_export_step_blocked_without_signoff_even_with_a_passing_fs(monkeypatch):
    """The bug this fix closes: a passing FS alone must not be enough — GET /export/step must
    enforce EVERY gate itself (including sign-off), not just hand back geometry because the client
    skipped the advisory POST /export/check step."""
    c = _client(monkeypatch)
    c.post("/analyze")  # FS now passes, but no sign-off yet
    resp = c.get("/export/step")
    assert resp.status_code == 409
    body = resp.json()
    assert any("not engineer-reviewed" in r for r in body["reasons"])
