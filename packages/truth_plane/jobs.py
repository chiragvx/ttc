"""Truth-Plane async analysis jobs (Dramatiq).

RedisBroker in the worker container (REDIS_URL set); StubBroker otherwise (tests, no Redis). The
serving app injects a verdict store + a job-status store via `configure`; defaults are no-ops so the
actor stays importable and unit-testable standalone.

2026-07-15 — `status_store` replaces the original `publish` callback. A plain Python callback can
only ever run inside the SAME process it was registered in; the actor body executes in the Dramatiq
WORKER process, a separate process from the web server that queues the job and polls for its result
(`packages/transport/app.py`'s `/analyze` and `/optimize`). Configuring `publish` in the web process
(as the code briefly did) was dead code — the worker's own `configure()` call, made once at worker
startup (`packages/truth_plane/worker.py`), is the only one whose `publish`/`status_store` value the
actor body ever actually sees. A durable, project_id-keyed store (in-memory for local/dev, Postgres
in compose — same split as the verdict store) is what actually lets the status written by the WORKER
be read back by the WEB process's poller, including after a restart.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

import dramatiq

from packages.ledger.derived_resolver import Verdict
from packages.truth_plane.analysis import analyze_in_subprocess, optimize_in_subprocess


def _make_broker():
    url = os.environ.get("REDIS_URL")
    if url:
        from dramatiq.brokers.redis import RedisBroker
        return RedisBroker(url=url)
    from dramatiq.brokers.stub import StubBroker
    return StubBroker()


broker = _make_broker()
dramatiq.set_broker(broker)


class VerdictStore(Protocol):
    def put_verdict(self, project_id: str, verdict: Verdict) -> None: ...


class JobStatusStore(Protocol):
    def put_status(self, project_id: str, status: str, message: Optional[str] = None) -> None: ...


_store: Optional[VerdictStore] = None
_status_store: Optional[JobStatusStore] = None


def configure(*, store: Optional[VerdictStore] = None,
              status_store: Optional[JobStatusStore] = None) -> None:
    global _store, _status_store
    _store, _status_store = store, status_store


@dramatiq.actor(max_retries=0, time_limit=600_000)
def run_fs_analysis(project_id: str, params: dict, material_name: str, load_n: float,
                    subsystem_name: str = "bracket", cut_features: list | None = None) -> None:
    if _status_store:
        _status_store.put_status(project_id, "running")
    try:
        verdict = analyze_in_subprocess(params, material_name, load_n, subsystem_name, cut_features=cut_features)
    except Exception as e:
        if _status_store:
            _status_store.put_status(project_id, "failed", message=str(e))
        raise
    if _store:
        _store.put_verdict(project_id, verdict)
    if _status_store:
        _status_store.put_status(project_id, "done")


@dramatiq.actor(max_retries=0, time_limit=900_000)
def run_optimization(project_id: str, candidates: list, base_params: dict, material_name: str,
                     load_n: float, fs_floor: float, subsystem_name: str = "bracket",
                     cut_features: list | None = None) -> None:
    if _status_store:
        _status_store.put_status(project_id, "running")
    try:
        result = optimize_in_subprocess(candidates, base_params, material_name, load_n, fs_floor,
                                        subsystem_name=subsystem_name, cut_features=cut_features)
    except Exception as e:
        if _status_store:
            _status_store.put_status(project_id, "failed", message=str(e))
        raise
    if _store:
        if result.get("best_verdict") is not None:
            _store.put_verdict(project_id, result["best_verdict"])
        _store.put_optimize(project_id, {"variants": result["variants"], "best_value": result["best_value"],
                                         "best_mass_g": result["best_mass_g"], "param_name": result["param_name"]})
    if _status_store:
        _status_store.put_status(project_id, "done")
