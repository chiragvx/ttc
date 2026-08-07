"""Generated-subsystem store — the durable, cross-project corpus of every LLM-driven custom-geometry
generation ATTEMPT (success or failure), tagged by which model (via OpenRouter) produced it.

Phase 2 of the AI-generated-custom-geometry initiative. The user's own explicit requirement: "ensure
that the server is ALWAYS capturing the outputs from the AI ... this will allow us to catalog" — every
attempt, not just registered/successful ones, so this module is built BEFORE the later correctness-
floor gate specifically so unconditional capture is structural, not a logging call a short-circuiting
code path could silently skip.

Deliberately NOT the same mechanism as `packages/ledger/events.py`'s new
`EventKind.GENERATED_SUBSYSTEM_ATTEMPT` pointer event:
  - THIS store holds the full row (code blob, sandbox output, etc.) and is CROSS-PROJECT — one growing
    corpus across everything any model has ever generated, regardless of which project asked for it.
  - The ledger event is a small, per-project, hash-chained POINTER (attempt_id/sha256/subsystem_name/
    model/outcome only) — durable proof-of-attempt inside that one project's own audit trail, mirroring
    `append_derivation`'s "pointer, not blob" shape exactly.
`put()` on this store and `append_generated_subsystem_attempt()` on the ledger are two separate calls a
caller makes together; neither implies the other, and this module does not import `packages.ledger` (no
ledger writes happen here).

`params` shape (coordinates with Phase 1's `sandbox_build_and_validate` params argument — no
`packages/truth_plane/sandbox_subsystem.py` exists yet in this working tree to import the real shape
from, so this documents the assumed one for later phases to match):
    [{"name": str, "default": float, "min": float, "max": float, "unit": str}, ...]
one dict per exposed build parameter.

DATABASE_URL-gated, same in-memory/Postgres split as `packages/truth_plane/verdict_store.py` +
`packages/ledger/event_store_pg.py::PgVerdictStore` (via
`packages/transport/app.py::_make_verdict_store`) — an HONEST IN-MEMORY FALLBACK, never a loud refusal.
This is deliberately different from `packages/truth_plane/jobs.py::_load_project_ledger`'s refusal:
that data is a specific project's own authoritative state (a bogus empty ledger there silently
misreports real instances as unknown), whereas this store is cross-cutting TELEMETRY — losing it on a
DATABASE_URL-less dev/test run is an honest, acceptable degradation, not a data-integrity risk.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Sane caps so a multi-KB (or runaway) sandbox log never balloons a row without bound. Applied by
# GenerationAttempt's own validators (see below) so the guarantee holds no matter which caller
# constructs one — not something a call site could forget to apply.
MAX_STDOUT_CHARS = 4000
MAX_STDERR_CHARS = 4000
MAX_REQUEST_EXCERPT_CHARS = 2000


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    marker = f"...[truncated, {len(s)} chars total]"
    return s[: max(0, limit - len(marker))] + marker


class GenerationAttempt(BaseModel):
    """One LLM-driven custom-subsystem generation attempt — captured unconditionally, whether it was
    ultimately registered or rejected, so the corpus this store builds is complete by construction."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    ts: str
    project_id: str                    # which project/ledger this was generated FROM (traceability only
                                        # — the store itself is cross-project, see module docstring)
    model: str                         # the real OpenRouter model identity that produced this code

    subsystem_name: str
    sha256: str                        # sha256 of `build_code`, same content-addressing convention as
                                        # `packages/ledger/events.py::append_derivation`
    build_code: str                    # the actual generated source
    params: list[dict] = Field(default_factory=list)  # see module docstring for the assumed shape

    sandbox_status: str                # e.g. "OK" / "ERROR" / "TIMEOUT_KILLED" — mirrors
                                        # `packages/truth_plane/sandbox.py::SandboxResult.status`
    sandbox_stdout: str = ""
    sandbox_stderr: str = ""
    volume_mm3: Optional[float] = None
    bbox_mm: Optional[list[float]] = None  # [x_mm, y_mm, z_mm] extents, if the sandbox computed one

    outcome: str                       # e.g. "registered" / "rejected"
    rejection_reason: Optional[str] = None
    user_request_excerpt: str = ""     # truncated NL request, for later human review context

    @field_validator("sandbox_stdout")
    @classmethod
    def _truncate_stdout(cls, v: str) -> str:
        return _truncate(v, MAX_STDOUT_CHARS)

    @field_validator("sandbox_stderr")
    @classmethod
    def _truncate_stderr(cls, v: str) -> str:
        return _truncate(v, MAX_STDERR_CHARS)

    @field_validator("user_request_excerpt")
    @classmethod
    def _truncate_request_excerpt(cls, v: str) -> str:
        return _truncate(v, MAX_REQUEST_EXCERPT_CHARS)


class GenerationAttemptStore(ABC):
    """Storage-pluggable, same split as `packages/ledger/events.py::BaseEventLog` (in-memory here,
    Postgres in `PgGenerationAttemptStore` below)."""

    @abstractmethod
    def put(self, attempt: GenerationAttempt) -> None: ...

    @abstractmethod
    def get(self, attempt_id: str) -> Optional[GenerationAttempt]: ...

    @abstractmethod
    def list(self, *, project_id: Optional[str] = None, limit: int = 100) -> list[GenerationAttempt]: ...


class InMemoryGenerationAttemptStore(GenerationAttemptStore):
    """Mirrors `verdict_store.py::InMemoryVerdictStore`'s own plain-dict style."""

    def __init__(self) -> None:
        self._rows: dict[str, GenerationAttempt] = {}

    def put(self, attempt: GenerationAttempt) -> None:
        self._rows[attempt.attempt_id] = attempt

    def get(self, attempt_id: str) -> Optional[GenerationAttempt]:
        return self._rows.get(attempt_id)

    def list(self, *, project_id: Optional[str] = None, limit: int = 100) -> list[GenerationAttempt]:
        rows = list(self._rows.values())
        if project_id is not None:
            rows = [r for r in rows if r.project_id == project_id]
        rows.reverse()  # most-recent-first (insertion order) -- a human review queue reads newest first
        return rows[:limit] if limit else rows


_DDL = [
    """CREATE TABLE IF NOT EXISTS generation_attempts (
        id SERIAL PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE, ts TEXT NOT NULL,
        project_id TEXT NOT NULL, model TEXT NOT NULL, subsystem_name TEXT NOT NULL,
        sha256 TEXT NOT NULL, build_code TEXT NOT NULL, params_json TEXT NOT NULL,
        sandbox_status TEXT NOT NULL, sandbox_stdout TEXT NOT NULL, sandbox_stderr TEXT NOT NULL,
        volume_mm3 DOUBLE PRECISION, bbox_mm_json TEXT, outcome TEXT NOT NULL,
        rejection_reason TEXT, user_request_excerpt TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_generation_attempts_project_id ON generation_attempts (project_id)",
]

_COLUMNS = (
    "attempt_id, ts, project_id, model, subsystem_name, sha256, build_code, params_json, "
    "sandbox_status, sandbox_stdout, sandbox_stderr, volume_mm3, bbox_mm_json, outcome, "
    "rejection_reason, user_request_excerpt"
)


def _connect(dsn: str | None = None):
    # Deliberately self-contained rather than reusing `event_store_pg._connect` — that function's own
    # `_DDL` list knows nothing about this module's table, and importing it would wrongly couple two
    # independent stores together. Same lazy-import/autocommit/idempotent-DDL shape as
    # `packages/ledger/event_store_pg.py::_connect`.
    import psycopg
    conn = psycopg.connect(dsn or os.environ["DATABASE_URL"], autocommit=True)
    for stmt in _DDL:
        try:
            conn.execute(stmt)
        except (psycopg.errors.UniqueViolation, psycopg.errors.DuplicateTable):
            pass  # CREATE TABLE/INDEX IF NOT EXISTS races across concurrent connections; it exists
    return conn


def _row_to_attempt(row) -> GenerationAttempt:
    (attempt_id, ts, project_id, model, subsystem_name, sha256, build_code, params_json,
     sandbox_status, sandbox_stdout, sandbox_stderr, volume_mm3, bbox_mm_json, outcome,
     rejection_reason, user_request_excerpt) = row
    return GenerationAttempt(
        attempt_id=attempt_id, ts=ts, project_id=project_id, model=model,
        subsystem_name=subsystem_name, sha256=sha256, build_code=build_code,
        params=json.loads(params_json), sandbox_status=sandbox_status,
        sandbox_stdout=sandbox_stdout, sandbox_stderr=sandbox_stderr, volume_mm3=volume_mm3,
        bbox_mm=json.loads(bbox_mm_json) if bbox_mm_json is not None else None,
        outcome=outcome, rejection_reason=rejection_reason,
        user_request_excerpt=user_request_excerpt,
    )


class PgGenerationAttemptStore(GenerationAttemptStore):
    """Real Postgres, mirrors `event_store_pg.py`'s connection/table-creation style. `attempt_id` is
    the natural idempotency key (`ON CONFLICT ... DO NOTHING`, same posture as
    `PgEventStore._put_artifact`'s content-addressed insert) — a generation attempt is written once."""

    def __init__(self, dsn: str | None = None) -> None:
        self.conn = _connect(dsn)

    @classmethod
    def from_env(cls) -> "PgGenerationAttemptStore":
        return cls()

    def put(self, attempt: GenerationAttempt) -> None:
        self.conn.execute(
            f"INSERT INTO generation_attempts ({_COLUMNS}) "
            f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            f"ON CONFLICT (attempt_id) DO NOTHING",
            (attempt.attempt_id, attempt.ts, attempt.project_id, attempt.model,
             attempt.subsystem_name, attempt.sha256, attempt.build_code,
             json.dumps(attempt.params), attempt.sandbox_status, attempt.sandbox_stdout,
             attempt.sandbox_stderr, attempt.volume_mm3,
             json.dumps(attempt.bbox_mm) if attempt.bbox_mm is not None else None,
             attempt.outcome, attempt.rejection_reason, attempt.user_request_excerpt),
        )

    def get(self, attempt_id: str) -> Optional[GenerationAttempt]:
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM generation_attempts WHERE attempt_id = %s", (attempt_id,)
        ).fetchone()
        return _row_to_attempt(row) if row else None

    def list(self, *, project_id: Optional[str] = None, limit: int = 100) -> list[GenerationAttempt]:
        if project_id is not None:
            rows = self.conn.execute(
                f"SELECT {_COLUMNS} FROM generation_attempts WHERE project_id = %s "
                f"ORDER BY id DESC LIMIT %s", (project_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"SELECT {_COLUMNS} FROM generation_attempts ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()
        return [_row_to_attempt(r) for r in rows]


def generation_attempt_store_from_env() -> GenerationAttemptStore:
    """DATABASE_URL-gated factory, same in-memory/Postgres split as
    `packages/transport/app.py::_make_verdict_store` — an honest in-memory fallback, never a loud
    refusal (see module docstring for why this store's cross-cutting-telemetry posture differs from
    `packages/truth_plane/jobs.py::_load_project_ledger`'s refusal)."""
    if os.environ.get("DATABASE_URL"):
        return PgGenerationAttemptStore.from_env()
    return InMemoryGenerationAttemptStore()
