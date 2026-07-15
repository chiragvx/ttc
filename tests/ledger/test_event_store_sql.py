"""Persistent SQL event store: parity with the in-memory log + durability across reconnect."""

from __future__ import annotations

from packages.ledger.deltas import ParameterDelta
from packages.ledger.event_store_sql import SqlEventStore
from packages.ledger.events import EventLog
from packages.ledger.schema import ReviewState

SKIN = "instances.root.params.skin_thickness_mm"
TS = "2026-06-28T00:00:00Z"


def _populate(log, base_ledger):
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.5), actor="ai", ts=TS)
    log.append_signoff("pe@example.com", ts=TS)
    return log


def test_sql_store_folds_like_in_memory(base_ledger):
    sql = _populate(SqlEventStore(), base_ledger)
    mem = _populate(EventLog(), base_ledger)
    assert sql.fold().model_dump() == mem.fold().model_dump()
    assert sql.verify_chain() is True


def test_events_since_queries_only_the_tail(base_ledger):
    """SqlEventStore overrides _events_since with a real WHERE seq >= ? query (2026-07-15, fold()'s
    snapshot cache) instead of the default full-fetch-then-slice — pins that it returns exactly the
    same events the default would, for a real sqlite-backed store."""
    store = _populate(SqlEventStore(), base_ledger)
    all_events = store.events()
    assert len(all_events) == 3  # genesis + mutation + signoff
    assert store._events_since(0) == all_events
    assert store._events_since(1) == all_events[1:]
    assert store._events_since(len(all_events)) == []


def test_sql_store_fold_cache_reflects_new_events_across_reads(base_ledger):
    """The same incremental-fold behavior EventLog gets, but backed by a real sqlite connection —
    confirms _events_since's WHERE-clause override composes correctly with fold()'s cache."""
    store = SqlEventStore()
    store.append_genesis(base_ledger, actor="system", ts=TS)
    store.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.0), actor="user", ts=TS)
    assert store.fold().instances["root"].params["skin_thickness_mm"].value == 3.0

    store.append_mutation(ParameterDelta(target_node=SKIN, requested_value=4.0), actor="user", ts=TS)
    assert store.fold().instances["root"].params["skin_thickness_mm"].value == 4.0


def test_sql_store_persists_across_reconnect(tmp_path, base_ledger):
    db = str(tmp_path / "events.db")
    store = _populate(SqlEventStore(db), base_ledger)
    sha = store.append_derivation("fs", b'{"fs": 4.05}', fingerprint="fp", actor="solver", ts=TS).payload["sha256"]
    store.close()

    reopened = SqlEventStore(db)  # fresh connection, same file
    led = reopened.fold()
    assert led.instances["root"].params["skin_thickness_mm"].value == 3.5
    assert led.review.state is ReviewState.ENGINEER_REVIEWED
    assert reopened.verify_chain() is True
    assert reopened.get_artifact(sha) == b'{"fs": 4.05}'
    # derivation did not leak into replay state
    assert reopened.fold().derived.factor_of_safety is None
