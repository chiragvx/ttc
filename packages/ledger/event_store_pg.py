"""Postgres-backed event store + verdict store (the durable, shared channel in compose).

Same FACTS/DERIVATIONS semantics as the in-memory/sqlite stores (BaseEventLog), over psycopg. In
compose the worker writes verdicts and the backend reads them from the SAME `verdicts` table; events
persist so projects survive restarts. psycopg is imported lazily so this module loads without it
(it's only installed in the worker/serve containers — the `worker` extra).

`events` is scoped by `project_id` (2026-07-15 fix — the table previously had NO scoping column at
all: every file, from every browser session, from every tenant, folded the exact same shared global
stream once DATABASE_URL was set, silently voiding session isolation the moment this store was in
play). `seq` is unique only WITHIN a project now (composite primary key), not globally — this is a
BREAKING schema change for anyone with an existing dev Postgres volume from before this fix; there is
still no migration tool (a known, separately-tracked gap), so `docker compose down -v` (drop the
volume) is the recovery path, not an in-place ALTER.
"""

from __future__ import annotations

import json
import os

from packages.ledger.derived_resolver import Verdict
from packages.ledger.events import BaseEventLog, Event, EventKind

_DDL = [
    """CREATE TABLE IF NOT EXISTS events (
        project_id TEXT NOT NULL DEFAULT '', seq INTEGER NOT NULL, kind TEXT NOT NULL,
        actor TEXT NOT NULL, ts TEXT NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL,
        hash TEXT NOT NULL, PRIMARY KEY (project_id, seq))""",
    "CREATE TABLE IF NOT EXISTS artifacts (sha256 TEXT PRIMARY KEY, content BYTEA NOT NULL)",
    """CREATE TABLE IF NOT EXISTS verdicts (
        id SERIAL PRIMARY KEY, project_id TEXT NOT NULL, geo_sig TEXT NOT NULL, fingerprint TEXT NOT NULL,
        verdict_json TEXT NOT NULL, created TIMESTAMPTZ DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS optimize_results (
        project_id TEXT PRIMARY KEY, result_json TEXT NOT NULL, created TIMESTAMPTZ DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS job_status (
        project_id TEXT PRIMARY KEY, status TEXT NOT NULL, message TEXT,
        updated TIMESTAMPTZ DEFAULT now())""",
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
    def __init__(self, dsn: str | None = None, project_id: str = "") -> None:
        self.conn = _connect(dsn)
        self.project_id = project_id

    @classmethod
    def from_env(cls, project_id: str = "") -> "PgEventStore":
        return cls(project_id=project_id)

    def _count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE project_id = %s", (self.project_id,)
        ).fetchone()[0]

    def _last_hash(self) -> str:
        return self.conn.execute(
            "SELECT hash FROM events WHERE project_id = %s ORDER BY seq DESC LIMIT 1", (self.project_id,)
        ).fetchone()[0]

    def _store_event(self, ev: Event) -> None:
        self.conn.execute(
            "INSERT INTO events (project_id, seq, kind, actor, ts, payload, prev_hash, hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (self.project_id, ev.seq, ev.kind.value, ev.actor, ev.ts, json.dumps(ev.payload),
             ev.prev_hash, ev.hash),
        )

    def _all_events(self) -> list[Event]:
        rows = self.conn.execute(
            "SELECT seq, kind, actor, ts, payload, prev_hash, hash FROM events "
            "WHERE project_id = %s ORDER BY seq", (self.project_id,)
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


class PgJobStatusStore:
    """Durable job-status channel across the web-process/worker-process boundary (2026-07-15 fix —
    see this module's docstring): the web process writes "queued" right after `.send()`, the worker
    writes "running"/"done"/"failed" as it actually executes, and any poller (in either process, or
    a fresh one after a restart) reads the SAME row — unlike the previous in-process `publish`
    callback, which the worker's own status updates never reached the web process at all."""

    def __init__(self, dsn: str | None = None) -> None:
        self.conn = _connect(dsn)

    @classmethod
    def from_env(cls) -> "PgJobStatusStore":
        return cls()

    def put_status(self, project_id: str, status: str, message: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO job_status (project_id, status, message) VALUES (%s, %s, %s) "
            "ON CONFLICT (project_id) DO UPDATE SET status = EXCLUDED.status, "
            "message = EXCLUDED.message, updated = now()",
            (project_id, status, message),
        )

    def get_status(self, project_id: str):
        from packages.truth_plane.verdict_store import JobStatus
        row = self.conn.execute(
            "SELECT status, message FROM job_status WHERE project_id = %s", (project_id,)
        ).fetchone()
        return JobStatus(status=row[0], message=row[1]) if row else None
