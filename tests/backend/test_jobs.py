"""Dramatiq FS-analysis actor wiring via StubBroker (no Redis, no kernel — analysis is faked).

2026-07-15 — status_store replaces the old `publish` callback: a plain in-process callback can't
cross the web-process/worker-process boundary at all (packages/truth_plane/jobs.py's module
docstring), so the failure path is the load-bearing addition here — before this fix, a crashed job
left every poller waiting forever with zero signal that anything went wrong."""

from __future__ import annotations

import dramatiq
import pytest
from dramatiq import Worker

from packages.ledger.derived_resolver import Verdict
from packages.ledger.nodes import SKIN
from packages.truth_plane import jobs
from packages.truth_plane.verdict_store import InMemoryJobStatusStore, InMemoryVerdictStore


@pytest.fixture
def worker():
    jobs.broker.emit_after("process_boot")
    dramatiq.set_broker(jobs.broker)
    w = Worker(jobs.broker, worker_timeout=100)
    w.start()
    yield w
    w.stop()
    jobs.broker.flush_all()


def test_actor_runs_stores_verdict_and_publishes_status(worker, monkeypatch):
    store = InMemoryVerdictStore()
    status_store = InMemoryJobStatusStore()
    jobs.configure(store=store, status_store=status_store)

    fake = Verdict(geometry_signature="sig", fingerprint="fp", factor_of_safety=5.0,
                   mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=3.0)
    monkeypatch.setattr(jobs, "analyze_in_subprocess",
                        lambda params, material_name, load_n, subsystem_name="bracket", cut_features=None: fake)

    jobs.run_fs_analysis.send("proj-1", {SKIN: 2.0}, "PLA", 40.0)
    jobs.broker.join(jobs.run_fs_analysis.queue_name)
    worker.join()

    assert store.verdicts("proj-1")[0].factor_of_safety == 5.0
    final = status_store.get_status("proj-1")
    assert final.status == "done"


def test_actor_failure_is_recorded_durably_not_silently_dropped(worker, monkeypatch):
    """The bug this fix closes: before status_store, a crashed job left the poller with NOTHING —
    indistinguishable from 'still running'. Now the failure (and its message) is durably recorded."""
    status_store = InMemoryJobStatusStore()
    jobs.configure(store=InMemoryVerdictStore(), status_store=status_store)

    def _boom(params, material_name, load_n, subsystem_name="bracket", cut_features=None):
        raise RuntimeError("solver exploded")

    monkeypatch.setattr(jobs, "analyze_in_subprocess", _boom)

    jobs.run_fs_analysis.send("proj-2", {SKIN: 2.0}, "PLA", 40.0)
    # StubBroker.join() re-raises the actor's own exception to the caller — test-harness behavior
    # (RedisBroker in production just logs it; max_retries=0 means no retry either way). The status
    # write inside the actor's except-block already ran before the exception propagates here.
    with pytest.raises(RuntimeError, match="solver exploded"):
        jobs.broker.join(jobs.run_fs_analysis.queue_name)
    worker.join()

    final = status_store.get_status("proj-2")
    assert final.status == "failed"
    assert "solver exploded" in final.message


def test_optimize_actor_publishes_running_then_done(worker, monkeypatch):
    store = InMemoryVerdictStore()
    status_store = InMemoryJobStatusStore()
    jobs.configure(store=store, status_store=status_store)

    observed_mid_run = {}

    def _fake_optimize(*a, **k):
        # captured from INSIDE the actor body -- proves "running" was written BEFORE the work
        # itself runs, not just retroactively alongside "done"
        observed_mid_run["status"] = status_store.get_status("proj-3").status
        return {"variants": [{"value": 3.0, "fs": 2.0, "mass_g": 10.0, "feasible": True}],
               "best_value": 3.0, "best_mass_g": 10.0, "best_verdict": None, "param_name": "thickness_mm"}

    monkeypatch.setattr(jobs, "optimize_in_subprocess", _fake_optimize)

    jobs.run_optimization.send("proj-3", [3.0], {SKIN: 2.0}, "PLA", 40.0, 1.5)
    jobs.broker.join(jobs.run_optimization.queue_name)
    worker.join()

    assert observed_mid_run["status"] == "running"
    assert store.get_optimize("proj-3")["best_value"] == 3.0
    assert status_store.get_status("proj-3").status == "done"
