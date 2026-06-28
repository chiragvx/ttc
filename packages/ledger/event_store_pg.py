"""Postgres-backed event store + verdict store (the durable, shared channel in compose).

Same FACTS/DERIVATIONS semantics as the in-memory/sqlite stores (BaseEventLog), over psycopg. In
compose the worker writes verdicts and the backend reads them from the SAME `verdicts` table; events
persist so projects survive restarts. psycopg is imported lazily so this module loads without it
(it's only installed in the worker/serve containers — the `worker` extra).
"""

from __future__ import annotations

import json
import os

from packages.ledger.derived_resolver import Verdict
from packages.ledger.events import BaseEventLog, Event, EventKind

_DDL = [
    """CREATE TABLE IF NOT EXISTS events (
        seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, actor TEXT NOT NULL, ts TEXT NOT NULL,
        payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL)""",
    "CREATE TABLE IF NOT EXISTS artifacts (sha256 TEXT PRIMARY KEY, content BYTEA NOT NULL)",
    """CREATE TABLE IF NOT EXISTS verdicts (
        id SERIAL PRIMARY KEY, project_id TEXT NOT NULL, geo_sig TEXT NOT NULL, fingerprint TEXT NOT NULL,
        verdict_json TEXT NOT NULL, created TIMESTAMPTZ DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS optimize_results (
        project_id TEXT PRIMARY KEY, result_json TEXT NOT NULL, created TIMESTAMPTZ DEFAULT now())""",
]


def _connect(dsn: str | None = None):
    import psycopg
    conn = psycopg.connect(dsn or os.environ["DATABASE_URL"], autocommit=True)
    for stmt in _DDL:
        try:
            conn.execute(stmt)
        except (psycopg.errors.UniqueViolation, psycopg.errors.DuplicateTable):
            pass  # CREATE TABLE IF NOT EXISTS races across concurrent connections; the table exists
    return conn


class PgEventStore(BaseEventLog):
    def __init__(self, dsn: str | None = None) -> None:
        self.conn = _connect(dsn)

    @classmethod
    def from_env(cls) -> "PgEventStore":
        return cls()

    def _count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def _last_hash(self) -> str:
        return self.conn.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()[0]

    def _store_event(self, ev: Event) -> None:
        self.conn.execute(
            "INSERT INTO events (seq, kind, actor, ts, payload, prev_hash, hash) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (ev.seq, ev.kind.value, ev.actor, ev.ts, json.dumps(ev.payload), ev.prev_hash, ev.hash),
        )

    def _all_events(self) -> list[Event]:
        rows = self.conn.execute(
            "SELECT seq, kind, actor, ts, payload, prev_hash, hash FROM events ORDER BY seq"
        ).fetchall()
        return [Event(seq=r[0], kind=EventKind(r[1]), actor=r[2], ts=r[3],
                      payload=json.loads(r[4]), prev_hash=r[5], hash=r[6]) for r in rows]

    def _put_artifact(self, sha256: str, content: bytes) -> None:
        self.conn.execute("INSERT INTO artifacts (sha256, content) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                          (sha256, content))

    def _get_artifact(self, sha256: str) -> bytes | None:
        row = self.conn.execute("SELECT content FROM artifacts WHERE sha256 = %s", (sha256,)).fetchone()
        return bytes(row[0]) if row else None


class PgVerdictStore:
    def __init__(self, dsn: str | None = None) -> None:
        self.conn = _connect(dsn)

    @classmethod
    def from_env(cls) -> "PgVerdictStore":
        return cls()

    def put_verdict(self, project_id: str, verdict: Verdict) -> None:
        self.conn.execute(
            "INSERT INTO verdicts (project_id, geo_sig, fingerprint, verdict_json) VALUES (%s,%s,%s,%s)",
            (project_id, verdict.geometry_signature, verdict.fingerprint, json.dumps(verdict.__dict__)),
        )

    def verdicts(self, project_id: str) -> list[Verdict]:
        rows = self.conn.execute(
            "SELECT verdict_json FROM verdicts WHERE project_id = %s ORDER BY id", (project_id,)
        ).fetchall()
        return [Verdict(**json.loads(r[0])) for r in rows]

    def put_optimize(self, project_id: str, result: dict) -> None:
        self.conn.execute(
            "INSERT INTO optimize_results (project_id, result_json) VALUES (%s, %s) "
            "ON CONFLICT (project_id) DO UPDATE SET result_json = EXCLUDED.result_json, created = now()",
            (project_id, json.dumps(result)),
        )

    def get_optimize(self, project_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT result_json FROM optimize_results WHERE project_id = %s", (project_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None
