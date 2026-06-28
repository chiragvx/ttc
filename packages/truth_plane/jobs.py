"""Truth-Plane async analysis jobs (Dramatiq).

RedisBroker in the worker container (REDIS_URL set); StubBroker otherwise (tests, no Redis). The
serving app injects a verdict store + a status publisher via `configure`; defaults are no-ops so the
actor stays importable and unit-testable standalone.
"""

from __future__ import annotations

import os
from typing import Callable, Optional, Protocol

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


_store: Optional[VerdictStore] = None
_publish: Optional[Callable[[str, str, Optional[Verdict]], None]] = None


def configure(*, store: Optional[VerdictStore] = None,
              publish: Optional[Callable[[str, str, Optional[Verdict]], None]] = None) -> None:
    global _store, _publish
    _store, _publish = store, publish


@dramatiq.actor(max_retries=0, time_limit=600_000)
def run_fs_analysis(project_id: str, params: dict, material_name: str, load_n: float) -> None:
    if _publish:
        _publish(project_id, "running", None)
    try:
        verdict = analyze_in_subprocess(params, material_name, load_n)
    except Exception:
        if _publish:
            _publish(project_id, "failed", None)
        raise
    if _store:
        _store.put_verdict(project_id, verdict)
    if _publish:
        _publish(project_id, "done", verdict)


@dramatiq.actor(max_retries=0, time_limit=900_000)
def run_optimization(project_id: str, candidates: list, rib: float, hole_dia: float, material_name: str,
                     load_n: float, fs_floor: float) -> None:
    if _publish:
        _publish(project_id, "optimizing", None)
    try:
        result = optimize_in_subprocess(candidates, rib, hole_dia, material_name, load_n, fs_floor)
    except Exception:
        if _publish:
            _publish(project_id, "failed", None)
        raise
    if _store:
        if result.get("best_verdict") is not None:
            _store.put_verdict(project_id, result["best_verdict"])
        _store.put_optimize(project_id, {"variants": result["variants"], "best_skin": result["best_skin"],
                                         "best_mass_g": result["best_mass_g"]})
    if _publish:
        _publish(project_id, "done", None)
