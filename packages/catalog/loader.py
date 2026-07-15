"""get_store() — picks the Postgres tier when DATABASE_URL is set, else the seed-file tier. Mirrors
packages/transport/app.py::_make_verdict_store()'s exact selection pattern.

A thin process-lifetime cache: reference data changes rarely within one process's life (unlike the
ever-growing event log), so re-resolving the store/re-reading JSON on every call would be pure waste.
`reset_cache()` exists for test isolation — tests that monkeypatch DATABASE_URL must call it, or a
prior test's cached store leaks across test boundaries."""

from __future__ import annotations

import os

from packages.catalog.store import DomainStore

_cached_store: DomainStore | None = None


def get_store() -> DomainStore:
    global _cached_store
    if _cached_store is not None:
        return _cached_store
    if os.environ.get("DATABASE_URL"):
        from packages.catalog.pg_store import PgCatalogStore
        _cached_store = PgCatalogStore.from_env()
    else:
        from packages.catalog.seed_store import SeedFileStore
        _cached_store = SeedFileStore()
    return _cached_store


def reset_cache() -> None:
    global _cached_store
    _cached_store = None
