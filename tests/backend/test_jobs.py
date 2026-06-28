"""Dramatiq FS-analysis actor wiring via StubBroker (no Redis, no kernel — analysis is faked)."""

from __future__ import annotations

import dramatiq
import pytest
from dramatiq import Worker

from packages.ledger.derived_resolver import Verdict
from packages.ledger.nodes import SKIN
from packages.truth_plane import jobs


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
    captured: dict = {}
    statuses: list[str] = []

    class Store:
        def put_verdict(self, project_id, verdict):
            captured["project"] = project_id
            captured["verdict"] = verdict

    jobs.configure(store=Store(), publish=lambda pid, s, v: statuses.append(s))
    fake = Verdict(geometry_signature="sig", fingerprint="fp", factor_of_safety=5.0,
                   mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=3.0)
    monkeypatch.setattr(jobs, "analyze_in_subprocess", lambda params, material_name, load_n: fake)

    jobs.run_fs_analysis.send("proj-1", {SKIN: 2.0}, "PLA", 40.0)
    jobs.broker.join(jobs.run_fs_analysis.queue_name)
    worker.join()

    assert captured["project"] == "proj-1"
    assert captured["verdict"].factor_of_safety == 5.0
    assert statuses == ["running", "done"]
