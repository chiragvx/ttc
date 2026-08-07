"""Generated-subsystem store: the cross-project corpus of every LLM-driven custom-geometry generation
ATTEMPT (packages/truth_plane/generated_subsystem_store.py). Round-trips both the in-memory and the
Postgres implementation, `list()` project_id filtering, truncation of oversized text fields, and the
DATABASE_URL-gated factory's honest in-memory fallback.

psycopg isn't installed in this dev environment (it's the worker/serve-only extra) -- the Postgres
tests below exercise PgGenerationAttemptStore's OWN SQL logic against a fake connection standing in for
a real Postgres table, same approach as tests/ledger/test_event_store_pg.py's own _FakeConn."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.truth_plane.generated_subsystem_store import (
    MAX_REQUEST_EXCERPT_CHARS,
    MAX_STDERR_CHARS,
    MAX_STDOUT_CHARS,
    GenerationAttempt,
    InMemoryGenerationAttemptStore,
    PgGenerationAttemptStore,
    generation_attempt_store_from_env,
)

TS = "2026-08-06T00:00:00Z"


def _make_attempt(attempt_id: str = "att_1", project_id: str = "proj_a", **overrides) -> GenerationAttempt:
    fields = dict(
        attempt_id=attempt_id, ts=TS, project_id=project_id, model="anthropic/claude-sonnet-4.5",
        subsystem_name="custom_bracket_v1", sha256="ab" * 32,
        build_code="def build(**p):\n    return box(10, 10, 10)\n",
        params=[{"name": "width_mm", "default": 10.0, "min": 1.0, "max": 50.0, "unit": "mm"}],
        sandbox_status="OK", sandbox_stdout="ok", sandbox_stderr="",
        volume_mm3=1000.0, bbox_mm=[10.0, 10.0, 10.0],
        outcome="registered", rejection_reason=None, user_request_excerpt="make me a bracket",
    )
    fields.update(overrides)
    return GenerationAttempt(**fields)


# --- GenerationAttempt model itself -------------------------------------------------------------


def test_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        GenerationAttempt(**{**_make_attempt().model_dump(), "bogus_field": 1})


def test_sandbox_stdout_and_stderr_are_truncated_to_a_sane_length():
    huge = "x" * (MAX_STDOUT_CHARS * 3)
    a = _make_attempt(sandbox_stdout=huge, sandbox_stderr=huge)
    assert len(a.sandbox_stdout) <= MAX_STDOUT_CHARS
    assert len(a.sandbox_stderr) <= MAX_STDERR_CHARS
    assert "truncated" in a.sandbox_stdout
    assert "truncated" in a.sandbox_stderr


def test_short_sandbox_output_is_left_untouched():
    a = _make_attempt(sandbox_stdout="short stdout", sandbox_stderr="short stderr")
    assert a.sandbox_stdout == "short stdout"
    assert a.sandbox_stderr == "short stderr"


def test_user_request_excerpt_is_truncated_to_a_sane_length():
    huge = "please build me a bracket " * 500
    assert len(huge) > MAX_REQUEST_EXCERPT_CHARS
    a = _make_attempt(user_request_excerpt=huge)
    assert len(a.user_request_excerpt) <= MAX_REQUEST_EXCERPT_CHARS
    assert "truncated" in a.user_request_excerpt


# --- InMemoryGenerationAttemptStore --------------------------------------------------------------


def test_in_memory_round_trip():
    store = InMemoryGenerationAttemptStore()
    attempt = _make_attempt()
    store.put(attempt)
    assert store.get("att_1") == attempt


def test_in_memory_get_missing_returns_none():
    store = InMemoryGenerationAttemptStore()
    assert store.get("nope") is None


def test_in_memory_list_filters_by_project_id():
    store = InMemoryGenerationAttemptStore()
    store.put(_make_attempt("att_1", project_id="proj_a"))
    store.put(_make_attempt("att_2", project_id="proj_b"))
    store.put(_make_attempt("att_3", project_id="proj_a"))

    proj_a = store.list(project_id="proj_a")
    assert {a.attempt_id for a in proj_a} == {"att_1", "att_3"}
    assert all(a.project_id == "proj_a" for a in proj_a)

    everything = store.list()
    assert {a.attempt_id for a in everything} == {"att_1", "att_2", "att_3"}


def test_in_memory_list_respects_limit_and_is_most_recent_first():
    store = InMemoryGenerationAttemptStore()
    for i in range(5):
        store.put(_make_attempt(f"att_{i}"))

    limited = store.list(limit=2)
    assert [a.attempt_id for a in limited] == ["att_4", "att_3"]  # most-recent-first


# --- PgGenerationAttemptStore (fake-connection SQL logic) ----------------------------------------


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows or []


_ROW_KEYS = (
    "attempt_id", "ts", "project_id", "model", "subsystem_name", "sha256", "build_code",
    "params_json", "sandbox_status", "sandbox_stdout", "sandbox_stderr", "volume_mm3",
    "bbox_mm_json", "outcome", "rejection_reason", "user_request_excerpt",
)


def _as_row(r: dict) -> tuple:
    return tuple(r[k] for k in _ROW_KEYS)


class _FakeConn:
    """Enough of a psycopg connection for PgGenerationAttemptStore: DDL no-ops, and the INSERT/SELECT
    shapes it actually issues, hand-matched against a shared in-memory list of dict rows -- mirrors
    tests/ledger/test_event_store_pg.py's own _FakeConn for the SAME reason (psycopg not installed)."""

    def __init__(self, shared_rows: list[dict]) -> None:
        self.rows = shared_rows

    def _next_id(self) -> int:
        return (max((r["id"] for r in self.rows), default=0)) + 1

    def execute(self, sql: str, params: tuple = ()):
        s = " ".join(sql.split())
        if s.startswith("CREATE TABLE") or s.startswith("CREATE INDEX"):
            return _Result(None)
        if s.startswith("INSERT INTO generation_attempts"):
            values = dict(zip(_ROW_KEYS, params))
            if any(r["attempt_id"] == values["attempt_id"] for r in self.rows):
                return _Result(None)  # ON CONFLICT (attempt_id) DO NOTHING
            values["id"] = self._next_id()
            self.rows.append(values)
            return _Result(None)
        if "WHERE attempt_id = " in s:
            (attempt_id,) = params
            matching = [r for r in self.rows if r["attempt_id"] == attempt_id]
            return _Result([_as_row(r) for r in matching[:1]])
        if "WHERE project_id = " in s and "ORDER BY id DESC LIMIT" in s:
            project_id, limit = params
            matching = sorted((r for r in self.rows if r["project_id"] == project_id),
                              key=lambda r: -r["id"])
            return _Result([_as_row(r) for r in matching[:limit]])
        if s.startswith("SELECT") and "FROM generation_attempts ORDER BY id DESC LIMIT" in s:
            (limit,) = params
            matching = sorted(self.rows, key=lambda r: -r["id"])
            return _Result([_as_row(r) for r in matching[:limit]])
        raise AssertionError(f"unexpected SQL against the fake connection: {s!r}")


@pytest.fixture
def fake_pg(monkeypatch):
    from packages.truth_plane import generated_subsystem_store as mod
    rows: list[dict] = []
    monkeypatch.setattr(mod, "_connect", lambda dsn=None: _FakeConn(rows))
    return rows


def test_pg_round_trip(fake_pg):
    store = PgGenerationAttemptStore()
    attempt = _make_attempt()
    store.put(attempt)
    assert store.get("att_1") == attempt


def test_pg_get_missing_returns_none(fake_pg):
    store = PgGenerationAttemptStore()
    assert store.get("nope") is None


def test_pg_put_is_idempotent_on_attempt_id(fake_pg):
    store = PgGenerationAttemptStore()
    attempt = _make_attempt()
    store.put(attempt)
    store.put(attempt)  # ON CONFLICT DO NOTHING -- must not raise or duplicate
    assert len(fake_pg) == 1


def test_pg_list_filters_by_project_id(fake_pg):
    store = PgGenerationAttemptStore()
    store.put(_make_attempt("att_1", project_id="proj_a"))
    store.put(_make_attempt("att_2", project_id="proj_b"))
    store.put(_make_attempt("att_3", project_id="proj_a"))

    proj_a = store.list(project_id="proj_a")
    assert {a.attempt_id for a in proj_a} == {"att_1", "att_3"}
    assert all(a.project_id == "proj_a" for a in proj_a)

    everything = store.list()
    assert {a.attempt_id for a in everything} == {"att_1", "att_2", "att_3"}


def test_pg_and_in_memory_agree_on_a_round_tripped_attempt(fake_pg):
    """Same GenerationAttempt through both implementations must come back equal -- proves neither
    store silently drops/reshapes a field (e.g. the Optional bbox_mm/volume_mm3/rejection_reason
    fields, which round-trip through JSON/NULL columns on the Postgres side)."""
    attempt = _make_attempt(rejection_reason=None, bbox_mm=None, volume_mm3=None)
    mem_store = InMemoryGenerationAttemptStore()
    mem_store.put(attempt)
    pg_store = PgGenerationAttemptStore()
    pg_store.put(attempt)

    assert mem_store.get("att_1") == pg_store.get("att_1") == attempt


# --- generation_attempt_store_from_env ------------------------------------------------------------


def test_factory_falls_back_to_in_memory_with_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = generation_attempt_store_from_env()
    assert isinstance(store, InMemoryGenerationAttemptStore)
    # cleanly usable, not a crash and not a refusal
    store.put(_make_attempt())
    assert store.get("att_1") is not None


def test_factory_uses_postgres_when_database_url_is_set(monkeypatch, fake_pg):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    store = generation_attempt_store_from_env()
    assert isinstance(store, PgGenerationAttemptStore)
