"""fold()'s snapshot cache (2026-07-15): a bare re-fold over the WHOLE event history on every read
(mesh render, telemetry poll, param fetch, WS response, …) was O(events-so-far) per call — a demo
session was fine, but the cost degrades toward quadratic over a longer one (reads x mutations-so-far).
BaseEventLog.fold() now caches the last-folded ledger and only replays events appended SINCE it."""

from __future__ import annotations

from packages.ledger.deltas import ParameterDelta
from packages.ledger import events as events_module
from packages.ledger.events import EventKind, EventLog

SKIN = "instances.root.params.skin_thickness_mm"
TS = "2026-06-28T00:00:00Z"


def _spy_replay(monkeypatch):
    """Wraps the real `replay` so tests can assert how many times it ran and over how many events,
    without faking its actual behavior (the wrapper still calls through -- state stays correct)."""
    calls: list[dict] = []
    real_replay = events_module.replay

    def _wrapped(events, reconcile=None, initial=None):
        events = list(events)
        calls.append({"n_events": len(events), "had_initial": initial is not None})
        return real_replay(events, reconcile=reconcile, initial=initial)

    monkeypatch.setattr(events_module, "replay", _wrapped)
    return calls


def test_repeated_fold_with_no_new_events_does_not_replay_at_all(base_ledger, monkeypatch):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.0), actor="user", ts=TS)

    calls = _spy_replay(monkeypatch)
    first = log.fold()
    assert len(calls) == 1  # cold: replays the whole (small) history once

    second = log.fold()
    assert len(calls) == 1  # warm, no new events: fold() must not call replay() again at all
    assert second.model_dump() == first.model_dump()


def test_new_events_since_the_last_fold_replay_only_the_suffix(base_ledger, monkeypatch):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.0), actor="user", ts=TS)

    calls = _spy_replay(monkeypatch)
    log.fold()
    assert calls[-1]["n_events"] == 2  # genesis + 1 mutation, cold

    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=4.0), actor="user", ts=TS)
    led = log.fold()
    assert len(calls) == 2
    assert calls[-1]["n_events"] == 1        # only the ONE new mutation, not the full history again
    assert calls[-1]["had_initial"] is True  # resumed from the cached ledger, not from genesis
    assert led.instances["root"].params["skin_thickness_mm"].value == 4.0

    # a THIRD fold with two more new events replays exactly those two, still not the whole history
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=4.5), actor="user", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=5.0), actor="user", ts=TS)
    led3 = log.fold()
    assert calls[-1]["n_events"] == 2
    assert led3.instances["root"].params["skin_thickness_mm"].value == 5.0


def test_cached_result_matches_a_full_cold_replay(base_ledger, monkeypatch):
    """The cache must be an optimization, never a behavior change: incremental folding across many
    small appends must land on EXACTLY the same state a single from-scratch replay would."""
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    for v in (3.0, 3.5, 4.0, 4.5, 5.0):
        log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=v), actor="user", ts=TS)
        log.fold()  # warms/advances the cache incrementally after each append

    incremental = log.fold()
    cold = events_module.replay(log.events())  # a totally independent from-scratch fold
    assert incremental.model_dump() == cold.model_dump()


def test_a_different_reconcile_callable_invalidates_the_cache(base_ledger, monkeypatch):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.0), actor="user", ts=TS)

    calls = _spy_replay(monkeypatch)
    reconcile_a = lambda led: led  # noqa: E731 -- distinct identity is all that matters here
    reconcile_b = lambda led: led  # noqa: E731

    log.fold(reconcile=reconcile_a)
    assert len(calls) == 1
    log.fold(reconcile=reconcile_a)
    assert len(calls) == 1  # same callable, no new events -> still a cache hit

    log.fold(reconcile=reconcile_b)
    assert len(calls) == 2  # different callable -> must NOT reuse reconcile_a's cached result
    assert calls[-1]["n_events"] == 2  # full re-fold, not a suffix -- the cache didn't apply at all

    log.fold(reconcile=None)
    assert len(calls) == 3  # None is ALSO a distinct identity from either callable


def test_events_since_matches_a_slice_of_all_events(base_ledger):
    """SqlEventStore/PgEventStore override _events_since with a real WHERE-seq>=N query; the default
    (used by EventLog) is a plain slice — this pins that the two must agree."""
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    for v in (3.0, 3.5, 4.0):
        log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=v), actor="user", ts=TS)

    all_events = log.events()
    assert log._events_since(0) == all_events
    assert log._events_since(2) == all_events[2:]
    assert log._events_since(len(all_events)) == []
