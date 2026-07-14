"""PgEventStore per-project scoping (2026-07-15 fix — the `events` table previously had NO scoping
column at all, so every file/session/tenant folded one shared global stream once DATABASE_URL was
set, silently voiding session isolation the moment this store was in play; a 2026-07-15 audit found
this live).

psycopg isn't installed in this dev environment (it's the `worker`/`serve` extra, container-only) —
these tests exercise PgEventStore's OWN SQL logic against a fake connection standing in for a real
Postgres table, not real Postgres itself. The fake shares one Python list across multiple PgEventStore
instances exactly the way real Postgres shares one table across multiple connections — the only thing
that can keep two projects apart is PgEventStore's own `WHERE project_id = %s` filtering."""

from __future__ import annotations

import pytest

from packages.ledger.deltas import ParameterDelta
from packages.ledger.events import EventKind


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows or []


class _FakeConn:
    """Enough of a psycopg connection for PgEventStore: DDL no-ops, and the four query shapes
    PgEventStore actually issues are hand-matched against a shared in-memory 'events' table (a plain
    list of dict rows) — standing in for what a real Postgres `WHERE project_id = %s` does."""

    def __init__(self, shared_rows: list[dict]) -> None:
        self.rows = shared_rows

    def execute(self, sql: str, params: tuple = ()):
        s = " ".join(sql.split())
        if s.startswith("CREATE TABLE") or s.startswith("CREATE INDEX"):
            return _Result(None)
        if s.startswith("SELECT COUNT(*) FROM events WHERE project_id"):
            (pid,) = params
            return _Result([(sum(1 for r in self.rows if r["project_id"] == pid),)])
        if s.startswith("SELECT hash FROM events WHERE project_id"):
            (pid,) = params
            matching = [r for r in self.rows if r["project_id"] == pid]
            if not matching:
                return _Result(None)
            newest = max(matching, key=lambda r: r["seq"])
            return _Result([(newest["hash"],)])
        if s.startswith("INSERT INTO events"):
            pid, seq, kind, actor, ts, payload, prev_hash, hash_ = params
            self.rows.append({"project_id": pid, "seq": seq, "kind": kind, "actor": actor, "ts": ts,
                              "payload": payload, "prev_hash": prev_hash, "hash": hash_})
            return _Result(None)
        if s.startswith("SELECT seq, kind, actor, ts, payload, prev_hash, hash FROM events WHERE project_id"):
            (pid,) = params
            matching = sorted((r for r in self.rows if r["project_id"] == pid), key=lambda r: r["seq"])
            return _Result([(r["seq"], r["kind"], r["actor"], r["ts"], r["payload"], r["prev_hash"], r["hash"])
                            for r in matching])
        raise AssertionError(f"unexpected SQL against the fake connection: {s!r}")


@pytest.fixture
def shared_table(monkeypatch):
    """Every PgEventStore created under this fixture shares ONE fake table — modeling exactly what
    happens in real Postgres: every FileState's own PgEventStore object points at the SAME database
    connection string/table, only `project_id` determines whether they're actually isolated."""
    from packages.ledger import event_store_pg
    rows: list[dict] = []
    monkeypatch.setattr(event_store_pg, "_connect", lambda dsn=None: _FakeConn(rows))
    return rows


def test_two_projects_on_the_shared_table_each_get_their_own_seq_numbering(shared_table, base_ledger):
    from packages.ledger.event_store_pg import PgEventStore

    alice = PgEventStore.from_env(project_id="alice_file")
    bob = PgEventStore.from_env(project_id="bob_file")
    alice.append_genesis(base_ledger, actor="system", ts="t0")
    bob.append_genesis(base_ledger, actor="system", ts="t0")

    assert alice._count() == 1
    assert bob._count() == 1
    assert [e.seq for e in alice._all_events()] == [0]
    assert [e.seq for e in bob._all_events()] == [0]  # NOT seq=1 -- own independent numbering


def test_a_mutation_on_one_project_never_appears_in_another(shared_table, base_ledger):
    from packages.ledger.event_store_pg import PgEventStore

    alice = PgEventStore.from_env(project_id="alice_file")
    bob = PgEventStore.from_env(project_id="bob_file")
    alice.append_genesis(base_ledger, actor="system", ts="t0")
    bob.append_genesis(base_ledger, actor="system", ts="t0")

    alice.append_mutation(ParameterDelta(target_node="instances.root.params.skin_thickness_mm",
                                         requested_value=9.0), actor="user", ts="t1")

    assert alice._count() == 2
    assert bob._count() == 1  # Bob's own count is completely unaffected by Alice's mutation
    assert EventKind.PARAMETER_MUTATION not in [e.kind for e in bob._all_events()]

    # cold replay of EACH project's own log reconstructs ONLY that project's history
    alice_led = alice.fold()
    bob_led = bob.fold()
    assert alice_led.instances["root"].params["skin_thickness_mm"].value == 9.0
    assert bob_led.instances["root"].params["skin_thickness_mm"].value == 2.0


def test_project_id_threads_through_from_transport_file_state(monkeypatch):
    """packages/transport/app.py::_make_event_log must pass the file's OWN id as project_id — the
    thing that actually closes the leak end to end."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    from packages.ledger import event_store_pg

    captured = {}

    class _RecordingStore:
        @classmethod
        def from_env(cls, project_id=""):
            captured["project_id"] = project_id
            return "a-fake-store"

    monkeypatch.setattr(event_store_pg, "PgEventStore", _RecordingStore)

    from packages.transport import app as app_module
    result = app_module._make_event_log("some_file_id_123")
    assert captured["project_id"] == "some_file_id_123"
    assert result == "a-fake-store"
