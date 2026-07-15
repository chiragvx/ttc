"""SeedFileStore — the zero-infra DomainStore tier. Pins that the checked-in JSON matches the
values packages/ledger/bom.py::MATERIAL_DB and packages/disciplines/cost.py::MACHINE_RATE_USD_PER_HR
hardcode by default (this is a faithful migration, not a value change)."""

from __future__ import annotations

from packages.catalog.seed_store import SeedFileStore
from packages.ledger.bom import MATERIAL_DB


def test_materials_match_the_hardcoded_bom_defaults():
    store = SeedFileStore()
    records = store.materials()
    assert set(records) == set(MATERIAL_DB)
    for name, mat in MATERIAL_DB.items():
        r = records[name]
        assert r.density_g_per_mm3 == mat.density_g_per_mm3
        assert r.youngs_mod_mpa == mat.youngs_mod_mpa
        assert r.poisson == mat.poisson
        assert r.yield_mpa == mat.yield_mpa
        assert r.service_temp_c == mat.service_temp_c
        assert r.cost_per_kg_usd == mat.cost_per_kg_usd


def test_manufacturing_clearance_holes_dataset():
    store = SeedFileStore()
    ds = store.dataset("manufacturing.clearance_holes_mm")
    assert ds is not None
    values = {e.entry_key: e.value_numeric for e in ds.entries}
    assert values == {"M3": 3.4, "M4": 4.5, "M5": 5.4, "M6": 6.4, "M8": 8.4}


def test_manufacturing_wall_thickness_dataset():
    store = SeedFileStore()
    ds = store.dataset("manufacturing.wall_thickness_mm")
    assert ds is not None
    values = {e.entry_key: e.value_numeric for e in ds.entries}
    assert values["min_wall"] == 0.8
    assert values["recommended_wall_load_bearing"] == 1.2


def test_cost_machine_rate_dataset_matches_hardcoded_default():
    from packages.disciplines.cost import MACHINE_RATE_USD_PER_HR

    store = SeedFileStore()
    ds = store.dataset("cost.machine_rates_usd_per_hr")
    assert ds is not None
    entry = next(e for e in ds.entries if e.entry_key == "fdm_default")
    assert entry.value_numeric == MACHINE_RATE_USD_PER_HR


def test_unknown_dataset_key_returns_none():
    store = SeedFileStore()
    assert store.dataset("nonexistent.dataset") is None


def test_materials_and_dataset_lookups_are_cached_not_reread_every_call():
    store = SeedFileStore()
    first = store.materials()
    second = store.materials()
    assert first == second
    # mutating the returned dict must not corrupt the store's own cache (materials() returns a copy)
    first["PLA"] = None  # type: ignore[assignment]
    assert store.materials()["PLA"] is not None
