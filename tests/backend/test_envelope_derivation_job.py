"""Dramatiq envelope-derivation actor wiring via StubBroker (2026-08-06, gearbox-housing-generation
initiative Phase 3) -- mirrors tests/backend/test_jobs.py's own StubBroker setup exactly (the SAME
default broker this repo already uses whenever REDIS_URL is unset, `packages/truth_plane/jobs.py`'s
own module docstring). UNLIKE run_fs_analysis/run_optimization (tested there), this actor also
durably WRITES its result -- `jobs._load_project_ledger` and `jobs.compute_envelope` are the two
collaborators these tests monkeypatch, the SAME "monkeypatch the actor's own module-level import"
technique test_jobs.py already uses for `analyze_in_subprocess`/`optimize_in_subprocess`.

`compute_envelope`'s own arithmetic (the real bbox/hull math) is already covered end to end by
tests/subsystems/test_envelope.py -- this file only proves `run_envelope_derivation`'s OWN wiring
around it: status transitions, the all-or-nothing apply_delta write-back, and durable persistence
through a real (in-memory) EventLog's `append_mutation`/`transaction()`."""

from __future__ import annotations

import dataclasses

import dramatiq
import pytest
from dramatiq import Worker

from packages.ledger.events import EventLog
from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Instance
from packages.subsystems import SUBSYSTEM_MODELS, SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems.base import EnvelopeSocketSpec
from packages.subsystems.envelope import EnvelopeComputeResult
from packages.truth_plane import jobs
from packages.truth_plane.verdict_store import InMemoryJobStatusStore

_HOUSING_TYPE = "_test_housing_job"


@pytest.fixture
def worker():
    jobs.broker.emit_after("process_boot")
    dramatiq.set_broker(jobs.broker)
    w = Worker(jobs.broker, worker_timeout=100)
    w.start()
    yield w
    w.stop()
    jobs.broker.flush_all()


def _pd(value: float) -> ParameterDef:
    return ParameterDef(value=value, unit="mm", bounds=(0.0, 1000.0))


@pytest.fixture
def housing_model(monkeypatch):
    """Registers a throwaway `_test_housing_job` Subsystem into SUBSYSTEM_MODELS with envelope_socket
    set -- mirrors tests/subsystems/test_envelope.py's own `housing_model` fixture.

    R3 FIX (2026-08-06, medium): also registers into SUBSYSTEM_REGISTRY now, mirroring
    tests/subsystems/test_envelope.py's `housing_model` fixture's OWN SUBSYSTEM_REGISTRY half exactly
    -- `run_envelope_derivation` now builds a `domain_checks` closure (get_subsystem(...)
    .check_invariants(...), the same apply_fit_op-mirroring wiring `_trigger_envelope_derivation`
    (packages/transport/app.py) got too) that `apply_delta` calls on every envelope-derived write, so
    `_test_housing_job` has to be a real, resolvable `get_subsystem(...)` entry the same way it already
    has to be a real, resolvable `get_subsystem_model(...)` entry -- not skippable here just because
    `compute_envelope` itself stays monkeypatched away."""
    base_model = get_subsystem_model("flat_bar")
    model = dataclasses.replace(
        base_model, name=_HOUSING_TYPE,
        envelope_socket=EnvelopeSocketSpec(dim_params={
            "hull_bbox_x_mm": "outer_width_mm", "hull_bbox_y_mm": "outer_depth_mm",
        }),
    )
    monkeypatch.setitem(SUBSYSTEM_MODELS, _HOUSING_TYPE, model)
    housing_ctx = dataclasses.replace(get_subsystem("flat_bar"), name=_HOUSING_TYPE)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, _HOUSING_TYPE, housing_ctx)
    return model


def _housing_ledger(base_ledger):
    """base_ledger's own root + a `_test_housing_job`-typed instance carrying two numeric derived-
    dimension params (outer_width_mm/outer_depth_mm, pre-seeded so apply_delta has a real target to
    write into) and a `wraps` list -- `wraps`' actual content is irrelevant here since
    `compute_envelope` itself is monkeypatched below (this file tests the actor's OWN wiring, not
    compute_envelope's arithmetic)."""
    housing = Instance(id="housing1", subsystem_type=_HOUSING_TYPE,
                       params={"outer_width_mm": _pd(10.0), "outer_depth_mm": _pd(10.0)},
                       parent_id=None, wraps=["root"])
    new_instances = dict(base_ledger.instances)
    new_instances["housing1"] = housing
    return base_ledger.model_copy(update={"instances": new_instances})


def _seeded_log(ledger) -> EventLog:
    log = EventLog()
    log.append_genesis(ledger, actor="system", ts="2026-01-01T00:00:00Z")
    return log


def test_actor_derives_and_durably_writes_envelope_dims(worker, monkeypatch, base_ledger, housing_model):
    log = _seeded_log(_housing_ledger(base_ledger))
    monkeypatch.setattr(jobs, "_load_project_ledger", lambda project_id: (log, log.fold()))
    monkeypatch.setattr(
        jobs, "compute_envelope",
        lambda ledger, housing_id: EnvelopeComputeResult(
            ok=True, values={"hull_bbox_x_mm": 42.0, "hull_bbox_y_mm": 7.0}))

    status_store = InMemoryJobStatusStore()
    jobs.configure(status_store=status_store)

    jobs.run_envelope_derivation.send("job-1", "proj-1", "housing1")
    jobs.broker.join(jobs.run_envelope_derivation.queue_name)
    worker.join()

    assert status_store.get_status("job-1").status == "done"
    final = log.fold()
    assert final.instances["housing1"].params["outer_width_mm"].value == 42.0
    assert final.instances["housing1"].params["outer_depth_mm"].value == 7.0


def test_actor_publishes_running_before_done(worker, monkeypatch, base_ledger, housing_model):
    log = _seeded_log(_housing_ledger(base_ledger))
    status_store = InMemoryJobStatusStore()
    jobs.configure(status_store=status_store)
    observed = {}

    def _fake_compute(ledger, housing_id):
        # captured from INSIDE the actor body -- proves "running" was written BEFORE the work itself
        # runs, not just retroactively alongside "done" (mirrors test_jobs.py's own
        # test_optimize_actor_publishes_running_then_done).
        observed["status"] = status_store.get_status("job-4").status
        return EnvelopeComputeResult(ok=True, values={"hull_bbox_x_mm": 1.0, "hull_bbox_y_mm": 1.0})

    monkeypatch.setattr(jobs, "_load_project_ledger", lambda project_id: (log, log.fold()))
    monkeypatch.setattr(jobs, "compute_envelope", _fake_compute)

    jobs.run_envelope_derivation.send("job-4", "proj-1", "housing1")
    jobs.broker.join(jobs.run_envelope_derivation.queue_name)
    worker.join()

    assert observed["status"] == "running"
    assert status_store.get_status("job-4").status == "done"


def test_actor_failure_when_compute_envelope_rejects_is_recorded_not_silently_dropped(
    worker, monkeypatch, base_ledger, housing_model,
):
    """Mirrors test_jobs.py's own test_actor_failure_is_recorded_durably_not_silently_dropped: a
    legitimate compute_envelope ok=False ("unknown", Inversion #1) must BLOCK, surfaced as a durable
    "failed" status with the real reason -- never silently treated as "done"."""
    log = _seeded_log(_housing_ledger(base_ledger))
    monkeypatch.setattr(jobs, "_load_project_ledger", lambda project_id: (log, log.fold()))
    monkeypatch.setattr(
        jobs, "compute_envelope",
        lambda ledger, housing_id: EnvelopeComputeResult(ok=False, reason="wraps list is empty"))

    status_store = InMemoryJobStatusStore()
    jobs.configure(status_store=status_store)

    jobs.run_envelope_derivation.send("job-2", "proj-1", "housing1")
    with pytest.raises(ValueError, match="wraps list is empty"):
        jobs.broker.join(jobs.run_envelope_derivation.queue_name)
    worker.join()

    final_status = status_store.get_status("job-2")
    assert final_status.status == "failed"
    assert "wraps list is empty" in final_status.message
    # NOT applied -- all-or-nothing, the ledger's params are untouched
    assert log.fold().instances["housing1"].params["outer_width_mm"].value == 10.0


def test_actor_failure_when_housing_instance_unknown(worker, monkeypatch, base_ledger):
    log = _seeded_log(base_ledger)
    monkeypatch.setattr(jobs, "_load_project_ledger", lambda project_id: (log, log.fold()))

    status_store = InMemoryJobStatusStore()
    jobs.configure(status_store=status_store)

    jobs.run_envelope_derivation.send("job-3", "proj-1", "ghost_housing")
    with pytest.raises(ValueError, match="unknown instance"):
        jobs.broker.join(jobs.run_envelope_derivation.queue_name)
    worker.join()

    assert status_store.get_status("job-3").status == "failed"


def test_actor_uses_a_separate_job_id_key_from_the_plain_project_id(
    worker, monkeypatch, base_ledger, housing_model,
):
    """run_fs_analysis/run_optimization both key status by the bare project_id (test_jobs.py's own
    tests use "proj-1"/"proj-2"/"proj-3" directly) -- this actor deliberately takes a SEPARATE job_id
    so an in-flight envelope derivation never stomps (or gets stomped by) a concurrent /analyze or
    /optimize job on the SAME project (run_envelope_derivation's own docstring)."""
    log = _seeded_log(_housing_ledger(base_ledger))
    monkeypatch.setattr(jobs, "_load_project_ledger", lambda project_id: (log, log.fold()))
    monkeypatch.setattr(
        jobs, "compute_envelope",
        lambda ledger, housing_id: EnvelopeComputeResult(ok=True, values={"hull_bbox_x_mm": 5.0}))

    status_store = InMemoryJobStatusStore()
    jobs.configure(status_store=status_store)
    status_store.put_status("proj-1", "running")  # a concurrent /analyze, keyed by the bare project_id

    jobs.run_envelope_derivation.send("proj-1:envelope", "proj-1", "housing1")
    jobs.broker.join(jobs.run_envelope_derivation.queue_name)
    worker.join()

    assert status_store.get_status("proj-1:envelope").status == "done"
    assert status_store.get_status("proj-1").status == "running"  # untouched
