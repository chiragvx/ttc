"""PgCatalogStore — the Postgres-backed DomainStore tier (compose today, Supabase later: pointing
DATABASE_URL at a hosted Supabase Postgres instance needs zero code change here, since Supabase IS
Postgres and this schema uses nothing but vanilla types/constraints).

Lives in its OWN `catalog` schema in the SAME database the ledger's event/verdict/job-status stores
already use (see docker-compose.yml's single `postgres` service) — not a second database/service.
`_connect()`/`_DDL` deliberately do NOT share code with packages/ledger/event_store_pg.py: a second
~20-line connect-and-run-ddl helper is cheap duplication, not worth a premature shared abstraction
for two call sites with genuinely different schemas.

psycopg is imported lazily (matches event_store_pg.py) so this module loads without it — it's the
`worker`/`serve` extra, not a core dependency."""

from __future__ import annotations

import json
import os

from packages.catalog.models import MaterialRecord, ReferenceDataset, ReferenceEntry

_DDL = [
    "CREATE SCHEMA IF NOT EXISTS catalog",
    """CREATE TABLE IF NOT EXISTS catalog.materials (
        name              TEXT PRIMARY KEY,
        density_g_per_mm3 DOUBLE PRECISION NOT NULL CHECK (density_g_per_mm3 > 0),
        youngs_mod_mpa    DOUBLE PRECISION NOT NULL CHECK (youngs_mod_mpa > 0),
        poisson           DOUBLE PRECISION NOT NULL CHECK (poisson >= 0 AND poisson < 0.5),
        yield_mpa         DOUBLE PRECISION NOT NULL CHECK (yield_mpa > 0),
        service_temp_c    DOUBLE PRECISION NOT NULL DEFAULT 50.0,
        cost_per_kg_usd   DOUBLE PRECISION NOT NULL DEFAULT 25.0,
        properties        JSONB NOT NULL DEFAULT '{}'::jsonb,
        source            TEXT,
        is_verified       BOOLEAN NOT NULL DEFAULT false,
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS catalog.reference_datasets (
        id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        key         TEXT NOT NULL UNIQUE,
        domain      TEXT NOT NULL,
        description TEXT,
        unit        TEXT,
        source      TEXT,
        version     TEXT,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS catalog.reference_entries (
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        dataset_id    BIGINT NOT NULL REFERENCES catalog.reference_datasets(id) ON DELETE CASCADE,
        entry_key     TEXT NOT NULL,
        value_numeric DOUBLE PRECISION,
        value_text    TEXT,
        unit          TEXT,
        attributes    JSONB NOT NULL DEFAULT '{}'::jsonb,
        source        TEXT,
        notes         TEXT,
        is_verified   BOOLEAN NOT NULL DEFAULT false,
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (dataset_id, entry_key))""",
]


def _connect(dsn: str | None = None):
    import psycopg
    conn = psycopg.connect(dsn or os.environ["DATABASE_URL"], autocommit=True)
    for stmt in _DDL:
        try:
            conn.execute(stmt)
        except (psycopg.errors.UniqueViolation, psycopg.errors.DuplicateTable, psycopg.errors.DuplicateSchema):
            pass  # CREATE ... IF NOT EXISTS races across concurrent connections; it exists already
    return conn


class PgCatalogStore:
    def __init__(self, dsn: str | None = None) -> None:
        self.conn = _connect(dsn)

    @classmethod
    def from_env(cls) -> "PgCatalogStore":
        return cls()

    # -- read (DomainStore protocol) --------------------------------------------------------------
    def materials(self) -> dict[str, MaterialRecord]:
        rows = self.conn.execute(
            "SELECT name, density_g_per_mm3, youngs_mod_mpa, poisson, yield_mpa, service_temp_c, "
            "cost_per_kg_usd, properties, source, is_verified FROM catalog.materials"
        ).fetchall()
        out: dict[str, MaterialRecord] = {}
        for r in rows:
            props = r[7] if isinstance(r[7], dict) else json.loads(r[7] or "{}")
            out[r[0]] = MaterialRecord(
                name=r[0], density_g_per_mm3=r[1], youngs_mod_mpa=r[2], poisson=r[3], yield_mpa=r[4],
                service_temp_c=r[5], cost_per_kg_usd=r[6], properties=props, source=r[8], is_verified=r[9],
            )
        return out

    def dataset(self, key: str) -> ReferenceDataset | None:
        row = self.conn.execute(
            "SELECT id, key, domain, description, unit, source, version "
            "FROM catalog.reference_datasets WHERE key = %s", (key,)
        ).fetchone()
        if row is None:
            return None
        ds_id, ds_key, domain, description, unit, source, version = row
        entry_rows = self.conn.execute(
            "SELECT entry_key, value_numeric, value_text, unit, attributes, source, notes, is_verified "
            "FROM catalog.reference_entries WHERE dataset_id = %s ORDER BY entry_key", (ds_id,)
        ).fetchall()
        entries = []
        for er in entry_rows:
            attrs = er[4] if isinstance(er[4], dict) else json.loads(er[4] or "{}")
            entries.append(ReferenceEntry(
                entry_key=er[0], value_numeric=er[1], value_text=er[2], unit=er[3],
                attributes=attrs, source=er[5], notes=er[6], is_verified=er[7],
            ))
        return ReferenceDataset(key=ds_key, domain=domain, description=description, unit=unit,
                                source=source, version=version, entries=entries)

    # -- write (used only by seed.py) --------------------------------------------------------------
    def upsert_materials(self, materials: list[MaterialRecord]) -> None:
        """Upsert every given material (JSON always wins), then PRUNE any row whose name is no
        longer present — see packages/catalog/CLAUDE.md's reseed-semantics note."""
        keep_names = [m.name for m in materials]
        for m in materials:
            self.conn.execute(
                "INSERT INTO catalog.materials (name, density_g_per_mm3, youngs_mod_mpa, poisson, "
                "yield_mpa, service_temp_c, cost_per_kg_usd, properties, source, is_verified) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (name) DO UPDATE SET density_g_per_mm3=EXCLUDED.density_g_per_mm3, "
                "youngs_mod_mpa=EXCLUDED.youngs_mod_mpa, poisson=EXCLUDED.poisson, "
                "yield_mpa=EXCLUDED.yield_mpa, service_temp_c=EXCLUDED.service_temp_c, "
                "cost_per_kg_usd=EXCLUDED.cost_per_kg_usd, properties=EXCLUDED.properties, "
                "source=EXCLUDED.source, is_verified=EXCLUDED.is_verified, updated_at=now()",
                (m.name, m.density_g_per_mm3, m.youngs_mod_mpa, m.poisson, m.yield_mpa,
                 m.service_temp_c, m.cost_per_kg_usd, json.dumps(m.properties), m.source, m.is_verified),
            )
        if keep_names:
            self.conn.execute(
                "DELETE FROM catalog.materials WHERE name != ALL(%s)", (keep_names,)
            )
        else:
            self.conn.execute("DELETE FROM catalog.materials")

    def upsert_dataset(self, dataset: ReferenceDataset) -> None:
        """Upsert one dataset + all its entries (JSON always wins), pruning entries removed from
        the JSON — see packages/catalog/CLAUDE.md's reseed-semantics note."""
        row = self.conn.execute(
            "INSERT INTO catalog.reference_datasets (key, domain, description, unit, source, version) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET domain=EXCLUDED.domain, description=EXCLUDED.description, "
            "unit=EXCLUDED.unit, source=EXCLUDED.source, version=EXCLUDED.version, updated_at=now() "
            "RETURNING id",
            (dataset.key, dataset.domain, dataset.description, dataset.unit, dataset.source, dataset.version),
        ).fetchone()
        ds_id = row[0]
        keep_keys = [e.entry_key for e in dataset.entries]
        for e in dataset.entries:
            self.conn.execute(
                "INSERT INTO catalog.reference_entries (dataset_id, entry_key, value_numeric, "
                "value_text, unit, attributes, source, notes, is_verified) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (dataset_id, entry_key) DO UPDATE SET value_numeric=EXCLUDED.value_numeric, "
                "value_text=EXCLUDED.value_text, unit=EXCLUDED.unit, attributes=EXCLUDED.attributes, "
                "source=EXCLUDED.source, notes=EXCLUDED.notes, is_verified=EXCLUDED.is_verified, "
                "updated_at=now()",
                (ds_id, e.entry_key, e.value_numeric, e.value_text, e.unit, json.dumps(e.attributes),
                 e.source, e.notes, e.is_verified),
            )
        if keep_keys:
            self.conn.execute(
                "DELETE FROM catalog.reference_entries WHERE dataset_id = %s AND entry_key != ALL(%s)",
                (ds_id, keep_keys),
            )
        else:
            self.conn.execute("DELETE FROM catalog.reference_entries WHERE dataset_id = %s", (ds_id,))
