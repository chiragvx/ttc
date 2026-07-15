"""DomainStore — the interface both storage tiers implement (packages/catalog/CLAUDE.md).

SeedFileStore (seed_store.py) is the zero-infra default; PgCatalogStore (pg_store.py) is the
Postgres-backed tier for compose/Supabase. loader.py::get_store() picks between them."""

from __future__ import annotations

from typing import Protocol

from packages.catalog.models import MaterialRecord, ReferenceDataset


class DomainStore(Protocol):
    def materials(self) -> dict[str, MaterialRecord]: ...
    def dataset(self, key: str) -> ReferenceDataset | None: ...
