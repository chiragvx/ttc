"""get_store() — Postgres when DATABASE_URL is set, else the seed-file store, mirroring
packages/transport/app.py::_make_verdict_store()'s exact selection pattern. Every test resets the
loader's process-lifetime cache in a fixture, since it's module-level state that would otherwise
leak across tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_loader_cache():
    from packages.catalog import loader
    loader.reset_cache()
    yield
    loader.reset_cache()


def test_no_database_url_uses_seed_file_store(monkeypatch):
    from packages.catalog.loader import get_store
    from packages.catalog.seed_store import SeedFileStore

    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = get_store()
    assert isinstance(store, SeedFileStore)


def test_database_url_set_uses_pg_store(monkeypatch):
    from packages.catalog import pg_store
    from packages.catalog.loader import get_store
    from packages.catalog.pg_store import PgCatalogStore

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    monkeypatch.setattr(pg_store, "_connect", lambda dsn=None: object())  # never actually queried here
    store = get_store()
    assert isinstance(store, PgCatalogStore)


def test_store_is_cached_across_calls(monkeypatch):
    from packages.catalog.loader import get_store

    monkeypatch.delenv("DATABASE_URL", raising=False)
    first = get_store()
    second = get_store()
    assert first is second


def test_reset_cache_forces_a_fresh_store(monkeypatch):
    from packages.catalog.loader import get_store, reset_cache

    monkeypatch.delenv("DATABASE_URL", raising=False)
    first = get_store()
    reset_cache()
    second = get_store()
    assert first is not second
