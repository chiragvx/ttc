"""PgCatalogStore — psycopg isn't installed in this dev environment (it's the `worker`/`serve`
extra, container-only), so these tests exercise PgCatalogStore's OWN SQL/upsert/prune logic against
a fake connection standing in for a real Postgres table — same technique as
tests/ledger/test_event_store_pg.py's _FakeConn/shared_table fixture."""

from __future__ import annotations

import pytest

from packages.catalog.models import MaterialRecord, ReferenceDataset, ReferenceEntry


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows or []


class _FakeConn:
    """Enough of a psycopg connection for PgCatalogStore: DDL no-ops, materials/reference tables
    modeled as plain in-memory dicts, upsert/prune/select hand-matched against the exact SQL
    PgCatalogStore issues."""

    def __init__(self) -> None:
        self.materials: dict[str, tuple] = {}       # name -> row tuple
        self.datasets: dict[str, int] = {}           # key -> id
        self.dataset_rows: dict[int, tuple] = {}      # id -> row tuple
        self.entries: dict[int, dict[str, tuple]] = {}  # dataset_id -> {entry_key: row tuple}
        self._next_id = 1

    def execute(self, sql: str, params: tuple = ()):
        s = " ".join(sql.split())

        if s.startswith("CREATE"):
            return _Result(None)

        if s.startswith("SELECT name, density_g_per_mm3"):
            return _Result(list(self.materials.values()))

        if s.startswith("INSERT INTO catalog.materials"):
            (name, density, e, poisson, yield_mpa, temp, cost, props, source, verified) = params
            self.materials[name] = (name, density, e, poisson, yield_mpa, temp, cost, props, source, verified)
            return _Result(None)

        if s.startswith("DELETE FROM catalog.materials WHERE name != ALL"):
            (keep,) = params
            for name in list(self.materials):
                if name not in keep:
                    del self.materials[name]
            return _Result(None)

        if s.startswith("DELETE FROM catalog.materials"):
            self.materials.clear()
            return _Result(None)

        if s.startswith("SELECT id, key, domain") and "reference_datasets" in s:
            (key,) = params
            if key not in self.datasets:
                return _Result([])
            return _Result([self.dataset_rows[self.datasets[key]]])

        if s.startswith("INSERT INTO catalog.reference_datasets"):
            (key, domain, description, unit, source, version) = params
            if key in self.datasets:
                ds_id = self.datasets[key]
            else:
                ds_id = self._next_id
                self._next_id += 1
                self.datasets[key] = ds_id
                self.entries[ds_id] = {}
            self.dataset_rows[ds_id] = (ds_id, key, domain, description, unit, source, version)
            return _Result([(ds_id,)])

        if s.startswith("SELECT entry_key, value_numeric"):
            (ds_id,) = params
            rows = sorted(self.entries.get(ds_id, {}).values(), key=lambda r: r[0])
            return _Result(rows)

        if s.startswith("INSERT INTO catalog.reference_entries"):
            (ds_id, entry_key, val_num, val_text, unit, attrs, source, notes, verified) = params
            self.entries.setdefault(ds_id, {})[entry_key] = (
                entry_key, val_num, val_text, unit, attrs, source, notes, verified)
            return _Result(None)

        if s.startswith("DELETE FROM catalog.reference_entries WHERE dataset_id = %s AND entry_key != ALL"):
            (ds_id, keep) = params
            for k in list(self.entries.get(ds_id, {})):
                if k not in keep:
                    del self.entries[ds_id][k]
            return _Result(None)

        if s.startswith("DELETE FROM catalog.reference_entries WHERE dataset_id"):
            (ds_id,) = params
            self.entries[ds_id] = {}
            return _Result(None)

        raise AssertionError(f"unexpected SQL against the fake connection: {s!r}")


@pytest.fixture
def fake_conn(monkeypatch):
    from packages.catalog import pg_store
    conn = _FakeConn()
    monkeypatch.setattr(pg_store, "_connect", lambda dsn=None: conn)
    return conn


def _material(name="PLA", **overrides):
    base = dict(name=name, density_g_per_mm3=0.00124, youngs_mod_mpa=3500.0, poisson=0.36,
               yield_mpa=50.0, service_temp_c=55.0, cost_per_kg_usd=22.0)
    base.update(overrides)
    return MaterialRecord(**base)


def test_upsert_and_read_materials(fake_conn):
    from packages.catalog.pg_store import PgCatalogStore

    store = PgCatalogStore.from_env()
    store.upsert_materials([_material("PLA"), _material("PETG", density_g_per_mm3=0.00127)])

    got = store.materials()
    assert set(got) == {"PLA", "PETG"}
    assert got["PETG"].density_g_per_mm3 == 0.00127


def test_reseed_upserts_changed_values_and_prunes_removed_rows(fake_conn):
    """The documented reseed semantics: JSON always wins on upsert, and a row whose key disappeared
    from the new seed set is deleted, not left as an orphan."""
    from packages.catalog.pg_store import PgCatalogStore

    store = PgCatalogStore.from_env()
    store.upsert_materials([_material("PLA"), _material("ABS")])
    assert set(store.materials()) == {"PLA", "ABS"}

    # second seed run: PLA's value changes, ABS is gone, PETG is new
    store.upsert_materials([_material("PLA", cost_per_kg_usd=99.0), _material("PETG")])
    got = store.materials()
    assert set(got) == {"PLA", "PETG"}  # ABS pruned
    assert got["PLA"].cost_per_kg_usd == 99.0  # PLA's new value won


def test_upsert_dataset_and_read_back(fake_conn):
    from packages.catalog.pg_store import PgCatalogStore

    store = PgCatalogStore.from_env()
    ds = ReferenceDataset(
        key="manufacturing.clearance_holes_mm", domain="manufacturing", unit="mm",
        entries=[ReferenceEntry(entry_key="M3", value_numeric=3.4),
                ReferenceEntry(entry_key="M4", value_numeric=4.5)],
    )
    store.upsert_dataset(ds)

    got = store.dataset("manufacturing.clearance_holes_mm")
    assert got is not None
    assert {e.entry_key: e.value_numeric for e in got.entries} == {"M3": 3.4, "M4": 4.5}


def test_reseed_dataset_prunes_removed_entries(fake_conn):
    from packages.catalog.pg_store import PgCatalogStore

    store = PgCatalogStore.from_env()
    ds1 = ReferenceDataset(key="k", domain="manufacturing",
                           entries=[ReferenceEntry(entry_key="a", value_numeric=1.0),
                                   ReferenceEntry(entry_key="b", value_numeric=2.0)])
    store.upsert_dataset(ds1)
    assert {e.entry_key for e in store.dataset("k").entries} == {"a", "b"}

    ds2 = ReferenceDataset(key="k", domain="manufacturing",
                           entries=[ReferenceEntry(entry_key="a", value_numeric=9.0)])
    store.upsert_dataset(ds2)
    got = store.dataset("k")
    assert {e.entry_key: e.value_numeric for e in got.entries} == {"a": 9.0}  # b pruned, a updated


def test_unknown_dataset_returns_none(fake_conn):
    from packages.catalog.pg_store import PgCatalogStore

    store = PgCatalogStore.from_env()
    assert store.dataset("nope") is None
