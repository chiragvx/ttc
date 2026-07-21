"""Persistent SQL event store: parity with the in-memory log + durability across reconnect."""

from __future__ import annotations

import pytest

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


def test_transaction_commits_every_append_together(base_ledger):
    """The normal (successful) case: several appends inside one transaction() block all land, exactly
    as if they'd been made outside one -- transaction() must not change WHAT gets persisted, only
    whether a mid-sequence failure can leave a partial write behind (see the next test)."""
    store = SqlEventStore()
    store.append_genesis(base_ledger, actor="system", ts=TS)
    with store.transaction():
        store.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.0), actor="cascade", ts=TS)
        store.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.5), actor="user", ts=TS)
    assert len(store.events()) == 3
    assert store.fold().instances["root"].params["skin_thickness_mm"].value == 3.5


def test_transaction_rolls_back_every_append_together_on_failure(base_ledger):
    """The bug this closes (foundations-audit H8): a logical mutation expressed as several events
    (e.g. cascade effects + their driver edit) used to be several independently-committed appends --
    a failure/crash between them could leave a cascade value durable with no driver edit to explain
    it. Inside a transaction() block, a failure partway through must leave NONE of the block's writes
    behind, not just the ones before the failure."""
    store = SqlEventStore()
    store.append_genesis(base_ledger, actor="system", ts=TS)

    class _BoomAfterFirst(Exception):
        pass

    with pytest.raises(_BoomAfterFirst):
        with store.transaction():
            store.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.0), actor="cascade", ts=TS)
            raise _BoomAfterFirst("simulated crash between the cascade event and the driver edit")

    # the cascade append must NOT have survived the rollback -- only genesis remains.
    assert len(store.events()) == 1
    assert store.fold().instances["root"].params["skin_thickness_mm"].value != 3.0


def test_nested_append_inside_a_transaction_does_not_deadlock_or_double_commit(base_ledger):
    """_append() and transaction() share the same (reentrant) lock; a transaction() block always
    contains one or more _append() calls made on the same thread -- confirms that composition is safe
    (no self-deadlock) and that the nested _append() calls don't each commit early, defeating the
    all-or-nothing guarantee the two tests above depend on."""
    store = SqlEventStore()
    store.append_genesis(base_ledger, actor="system", ts=TS)
    with store.transaction():
        assert store._in_transaction is True
        store.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.0), actor="cascade", ts=TS)
        assert store._in_transaction is True  # _append() didn't reset it on the way out
    assert store._in_transaction is False
    assert len(store.events()) == 2


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
