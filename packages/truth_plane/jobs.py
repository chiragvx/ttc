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

from packages.ledger.apply import ApplyStatus, apply_delta
from packages.ledger.deltas import ParameterDelta
from packages.ledger.derived_resolver import Verdict
from packages.subsystems.envelope import compute_envelope, housing_alignment_transform
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


# --- run_envelope_derivation (2026-08-06, gearbox-housing-generation initiative Phase 3) -------------
# One new Dramatiq actor, copy-adapted from `run_fs_analysis`'s exact shape (same status-write-before-
# work / try-except-write-failure-then-reraise pattern; see this module's own docstring for the
# RedisBroker/StubBroker split every actor here shares). UNLIKE the two FS-solver actors above, this one
# also durably WRITES its result — a housing's derived-envelope dims are geometry/construction-grade,
# not a live safety scalar (this initiative's own Phase 2 "FitBinding, not Coupling" precedent), so they
# get written ONCE via the ordinary `ParameterDelta`/`apply_delta` path, mirroring
# `packages/ledger/apply.py::apply_fit_op`'s own "loop result.values, apply each as an ordinary
# ParameterDelta, all-or-nothing" pattern one layer out — never a special-cased write path
# (packages/ledger/CLAUDE.md).

_JOB_TS = "2026-06-28T00:00:00Z"  # mirrors packages/transport/app.py's own fixed `_TS` convention —
                                   # this whole codebase doesn't yet stamp real wall-clock event times
                                   # (every append_* call across the app uses the same fixed literal);
                                   # copied verbatim rather than inventing a different convention here.


def _load_project_ledger(project_id: str):
    """DATABASE_URL-gated durable-log reload, mirroring `packages/transport/app.py::_make_event_log`'s
    own Postgres-in-compose / in-memory-otherwise split. Duplicated here rather than imported —
    `packages.transport` is a higher layer that itself imports THIS module (`from packages.truth_plane
    import jobs`), so importing back would be circular, and this package must stay standalone-
    importable (this module's own docstring: the actor body runs in a separate WORKER process that
    never touches `packages.transport.app`). Returns `(log, ledger)` — `ledger` is None if the log has
    no GENESIS event yet — so a caller can both read CURRENT state and append new durable facts through
    the SAME log instance afterward.

    R1 FIX (2026-08-06, medium): this WORKER process can only ever see a project's real ledger through
    Postgres (`DATABASE_URL`) — unlike the web process, it has no in-memory copy of anyone's design to
    fall back to. The original code, when `DATABASE_URL` was unset, silently built a FRESH, empty,
    private `EventLog()` on every call instead of failing loudly; that log's `fold()` always returns
    `ledger=None` (no GENESIS event), which `run_envelope_derivation` then turned into a misleading
    `ValueError(f"unknown instance {housing_instance_id!r}")` — a real, durably-existing instance
    misreported as unknown, purely because the worker had no way to load it, not because it doesn't
    exist. Rather than fabricate that empty log (a fabricated-green-light-shaped failure — CLAUDE.md's
    "never a fabricated green light", generalized from safety scalars to ledger loads here), this now
    raises immediately so the real cause (a worker started without `DATABASE_URL`) surfaces as the job's
    "failed" status message instead of a bogus per-instance diagnosis. This is unconditional on
    `REDIS_URL`: no value of `DATABASE_URL`-less `EventLog()` could ever legitimately contain
    `project_id`'s real events, so there is no benign case to preserve. In the fully-synchronous local
    dev shape this repo's docker-compose.yml ships (`REDIS_URL` unset), this function is never reached
    at all — `/envelope_ops`'s synchronous fallback (packages/transport/app.py::
    _trigger_envelope_derivation) handles it in-process against the REAL ledger instead."""
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            f"run_envelope_derivation: DATABASE_URL is not set in this worker process, so "
            f"project_id={project_id!r} cannot be durably reloaded here — refusing to fabricate a "
            f"fresh, empty in-memory ledger, which would misreport every housing_instance_id as an "
            f"unknown instance instead of surfacing the real problem. Set DATABASE_URL on the worker "
            f"(see docker-compose.yml) so it shares the web process's durable event log."
        )
    from packages.ledger.event_store_pg import PgEventStore
    from packages.subsystems.assembly_template import reconcile_all
    log = PgEventStore.from_env(project_id=project_id)
    return log, log.fold(reconcile=reconcile_all)


@dramatiq.actor(max_retries=0, time_limit=180_000)
def run_envelope_derivation(job_id: str, project_id: str, housing_instance_id: str) -> None:
    """Derive `housing_instance_id`'s outer-envelope dimensions (`packages/subsystems/envelope.py::
    compute_envelope`, Phase 2) and write them into its own params. `time_limit` 180s — shorter than
    `run_fs_analysis`'s 600s / `run_optimization`'s 900s: this is real OCCT geometry (one group bbox +
    one convex-hull build over `housing_instance_id`'s wrapped members, `packages/subsystems/
    geometry_query.py`), not an FEA mesh/solve or a 4-candidate FEA sweep — orders of magnitude cheaper
    per call, so a much shorter ceiling is still generous.

    `job_id` (the status-store key, e.g. f"{project_id}:envelope:{housing_instance_id}") is DELIBERATELY
    separate from `project_id` (the ledger's own durable-store scoping key, `_load_project_ledger`'s
    argument): unlike `run_fs_analysis`/`run_optimization`, which both key job status by the bare
    `project_id` (and so already stomp each other if queued concurrently on the same project —
    pre-existing, not touched here), an envelope derivation gets its OWN status row so it doesn't
    collide with a concurrently in-flight /analyze or /optimize job on the same project. It is further
    scoped by `housing_instance_id` (2026-08-06 repair — R3 CONFIRMED, medium): a project can hold more
    than one housing, and each derivation is itself per-housing, so a key shared across housings would
    let two concurrent derivations (two different housings, or a retried wrap_group on the SAME
    housing) race on one status slot with last-write-wins — see packages/transport/app.py's
    `_trigger_envelope_derivation`/`envelope_status` for the caller side of this."""
    if _status_store:
        _status_store.put_status(job_id, "running")
    try:
        log, ledger = _load_project_ledger(project_id)
        housing = ledger.instances.get(housing_instance_id) if ledger is not None else None
        if housing is None:
            raise ValueError(f"unknown instance {housing_instance_id!r}")
        result = compute_envelope(ledger, housing_instance_id)
        if not result.ok:
            raise ValueError(result.reason or "envelope could not be computed")
        from packages.subsystems import get_subsystem, get_subsystem_model
        model = get_subsystem_model(housing.subsystem_type)
        if model.envelope_socket is None:
            raise ValueError(f"{housing.subsystem_type!r} declares no envelope_socket")
        working = ledger
        deltas: list[ParameterDelta] = []
        # R3 FIX (2026-08-06, medium): mirror apply_fit_op's `domain_checks` wiring (packages/ledger/
        # apply.py:1321-1325, the pattern this actor is explicitly built to follow — see this module's
        # own header comment) and app.py's `_trigger_envelope_derivation` synchronous branch, fixed
        # identically — the housing's own subsystem-level invariants must gate an envelope-derived
        # write exactly like the ordinary hand-typed WS mutation path already does (app.py:1144-1147),
        # not be silently bypassed just because the value was derived rather than typed.
        domain_checks = lambda led: get_subsystem(housing.subsystem_type).check_invariants(  # noqa: E731
            led, housing_instance_id)
        for key, target_param in model.envelope_socket.dim_params.items():
            if key not in result.values:
                continue
            d = ParameterDelta(target_node=f"instances.{housing_instance_id}.params.{target_param}",
                               requested_value=result.values[key],
                               rationale="derived from wrap_group envelope")
            working, outcome = apply_delta(working, d, domain_checks=domain_checks)
            if outcome.status in (ApplyStatus.REJECTED, ApplyStatus.CONFLICT):
                raise ValueError(f"{target_param}: {outcome.message} — envelope NOT applied "
                                 f"(all-or-nothing)")
            deltas.append(d)

        # R5 FIX (2026-08-06, CONFIRMED, high — see packages/subsystems/envelope.py's own module
        # docstring "Fix note"): SIZE alone doesn't make a housing actually contain what it wraps if its
        # POSITION is untethered from the wrapped group's own real world position. Align the housing's
        # own Transform to the group's real world center, in the SAME all-or-nothing transaction as the
        # size write above — a housing's position is now just as derived, not guessed, as its size.
        new_transform = housing_alignment_transform(working, housing_instance_id, result)
        moved = False
        if new_transform is not None:
            current = working.instances[housing_instance_id].transform
            moved = (current is None or abs(current.x_mm - new_transform.x_mm) > 1e-9
                     or abs(current.y_mm - new_transform.y_mm) > 1e-9
                     or abs(current.z_mm - new_transform.z_mm) > 1e-9)
            if moved:
                new_instances = dict(working.instances)
                new_instances[housing_instance_id] = working.instances[housing_instance_id].model_copy(
                    update={"transform": new_transform})
                working = working.model_copy(update={"instances": new_instances})

        with log.transaction():
            for d in deltas:
                log.append_mutation(d, actor="envelope_derivation", ts=_JOB_TS)
            if moved:
                log.append_instance_moved(housing_instance_id, new_transform,
                                          actor="envelope_derivation", ts=_JOB_TS)
    except Exception as e:
        if _status_store:
            _status_store.put_status(job_id, "failed", message=str(e))
        raise
    if _status_store:
        _status_store.put_status(job_id, "done")
