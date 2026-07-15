"""Persistent SQL event store — same FACTS/DERIVATIONS semantics as the in-memory log, durably.

Implemented on sqlite3 (stdlib, testable anywhere). The schema and queries are Postgres-portable: the
production store is a driver swap (psycopg) over the same `events` / `artifacts` tables — `payload`
becomes JSONB, `content` becomes BYTEA, `?` placeholders become `%s`. One ordered stream per
project/branch (one DB / table-namespace per stream).
"""

from __future__ import annotations

import json
import sqlite3

from packages.ledger.events import BaseEventLog, Event, EventKind

_DDL = """
CREATE TABLE IF NOT EXISTS events (
  seq       INTEGER PRIMARY KEY,
  kind      TEXT NOT NULL,
  actor     TEXT NOT NULL,
  ts        TEXT NOT NULL,
  payload   TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  sha256  TEXT PRIMARY KEY,
  content BLOB NOT NULL
);
"""


class SqlEventStore(BaseEventLog):
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_DDL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def _last_hash(self) -> str:
        row = self.conn.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0]

    def _store_event(self, ev: Event) -> None:
        self.conn.execute(
            "INSERT INTO events (seq, kind, actor, ts, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
            (ev.seq, ev.kind.value, ev.actor, ev.ts, json.dumps(ev.payload), ev.prev_hash, ev.hash),
        )
        self.conn.commit()

    def _all_events(self) -> list[Event]:
        rows = self.conn.execute(
            "SELECT seq, kind, actor, ts, payload, prev_hash, hash FROM events ORDER BY seq"
        ).fetchall()
        return [Event(seq=r[0], kind=EventKind(r[1]), actor=r[2], ts=r[3],
                      payload=json.loads(r[4]), prev_hash=r[5], hash=r[6]) for r in rows]

    def _events_since(self, count: int) -> list[Event]:
        # a cache-hit fold() only needs the TAIL — avoids re-fetching/re-deserializing the whole
        # history from disk on every read (see BaseEventLog.fold()'s docstring).
        rows = self.conn.execute(
            "SELECT seq, kind, actor, ts, payload, prev_hash, hash FROM events WHERE seq >= ? ORDER BY seq",
            (count,),
        ).fetchall()
        return [Event(seq=r[0], kind=EventKind(r[1]), actor=r[2], ts=r[3],
                      payload=json.loads(r[4]), prev_hash=r[5], hash=r[6]) for r in rows]

    def _put_artifact(self, sha256: str, content: bytes) -> None:
        self.conn.execute("INSERT OR REPLACE INTO artifacts (sha256, content) VALUES (?, ?)", (sha256, content))
        self.conn.commit()

    def _get_artifact(self, sha256: str) -> bytes | None:
        row = self.conn.execute("SELECT content FROM artifacts WHERE sha256 = ?", (sha256,)).fetchone()
        return bytes(row[0]) if row else None
