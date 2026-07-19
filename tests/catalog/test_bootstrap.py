"""apply_to_live_app() — the one function that wires packages.catalog into the running app. Each
override is independently fault-tolerant: a failure in the catalog store must never crash the app or
block the OTHER override (packages/catalog/bootstrap.py's own docstring)."""

from __future__ import annotations

import pytest

from packages.catalog.models import MaterialRecord, ReferenceDataset, ReferenceEntry
from packages.disciplines import cost as cost_module
from packages.disciplines import manufacturing as manufacturing_module
from packages.ledger import bom
from packages.ledger import wire_ampacity as wire_ampacity_module


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    bom.reset_material_db()
    cost_module.reset_machine_rate()
    manufacturing_module.reset_dfm_reference()
    wire_ampacity_module.reset_wire_ampacity_db()


class _FakeStore:
    def __init__(self, materials=None, datasets=None, raise_on="") -> None:
        self._materials = materials or {}
        self._datasets = datasets or {}
        self._raise_on = raise_on

    def materials(self):
        if self._raise_on == "materials":
            raise RuntimeError("boom")
        return dict(self._materials)

    def dataset(self, key):
        if self._raise_on == "dataset":
            raise RuntimeError("boom")
        return self._datasets.get(key)


def _patch_store(monkeypatch, store) -> None:
    from packages.catalog import loader
    monkeypatch.setattr(loader, "get_store", lambda: store)


def test_apply_overrides_material_db(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    fake = _FakeStore(materials={
        "PLA": MaterialRecord(name="PLA", density_g_per_mm3=9.99, youngs_mod_mpa=1.0, poisson=0.3,
                              yield_mpa=1.0, service_temp_c=1.0, cost_per_kg_usd=1.0),
    })
    _patch_store(monkeypatch, fake)

    apply_to_live_app()
    assert bom.material("PLA").density_g_per_mm3 == 9.99


def test_apply_overrides_machine_rate(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    fake = _FakeStore(datasets={
        "cost.machine_rates_usd_per_hr": ReferenceDataset(
            key="cost.machine_rates_usd_per_hr", domain="cost",
            entries=[ReferenceEntry(entry_key="fdm_default", value_numeric=42.0)],
        ),
    })
    _patch_store(monkeypatch, fake)

    apply_to_live_app()
    assert cost_module.MACHINE_RATE_USD_PER_HR == 42.0


def test_materials_failure_does_not_block_machine_rate_or_crash(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    fake = _FakeStore(
        raise_on="materials",
        datasets={"cost.machine_rates_usd_per_hr": ReferenceDataset(
            key="cost.machine_rates_usd_per_hr", domain="cost",
            entries=[ReferenceEntry(entry_key="fdm_default", value_numeric=7.0)])},
    )
    _patch_store(monkeypatch, fake)

    apply_to_live_app()  # must not raise
    assert bom.material("PLA").density_g_per_mm3 == bom._DEFAULT_MATERIAL_DB["PLA"].density_g_per_mm3
    assert cost_module.MACHINE_RATE_USD_PER_HR == 7.0  # the OTHER override still applied


def test_missing_machine_rate_entry_leaves_the_default(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    fake = _FakeStore(datasets={
        "cost.machine_rates_usd_per_hr": ReferenceDataset(
            key="cost.machine_rates_usd_per_hr", domain="cost", entries=[]),  # no fdm_default entry
    })
    _patch_store(monkeypatch, fake)

    apply_to_live_app()
    assert cost_module.MACHINE_RATE_USD_PER_HR == cost_module._DEFAULT_MACHINE_RATE_USD_PER_HR


def test_empty_materials_leaves_the_default(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    _patch_store(monkeypatch, _FakeStore(materials={}))
    apply_to_live_app()
    assert bom.MATERIAL_DB == bom._DEFAULT_MATERIAL_DB


def test_apply_overrides_manufacturing_dfm(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    fake = _FakeStore(datasets={
        "manufacturing.clearance_holes_mm": ReferenceDataset(
            key="manufacturing.clearance_holes_mm", domain="manufacturing",
            entries=[ReferenceEntry(entry_key="M5", value_numeric=5.5)]),
        "manufacturing.wall_thickness_mm": ReferenceDataset(
            key="manufacturing.wall_thickness_mm", domain="manufacturing",
            entries=[ReferenceEntry(entry_key="recommended_wall_load_bearing", value_numeric=3.3),
                    ReferenceEntry(entry_key="min_wall", value_numeric=0.5)]),  # must NOT be applied
    })
    _patch_store(monkeypatch, fake)

    apply_to_live_app()
    text = manufacturing_module._fragment()
    assert "M5→5.5" in text
    assert "≥ 3.3 mm recommended" in text
    # the hard floor is NEVER sourced from the catalog, even though this dataset carries a
    # (deliberately different, to prove it's ignored) min_wall entry
    from packages.ledger.apply import MIN_WALL_MM
    assert f"Minimum wall is {MIN_WALL_MM:g} mm" in text


def test_apply_overrides_wire_ampacity(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    fake = _FakeStore(datasets={
        "electrical.wire_ampacity_amps": ReferenceDataset(
            key="electrical.wire_ampacity_amps", domain="electrical",
            entries=[ReferenceEntry(entry_key="AWG10", value_numeric=99.0)]),
    })
    _patch_store(monkeypatch, fake)

    apply_to_live_app()
    assert wire_ampacity_module.ampacity_a("AWG10") == 99.0


def test_missing_wire_ampacity_dataset_leaves_the_default(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    _patch_store(monkeypatch, _FakeStore(datasets={}))
    apply_to_live_app()
    assert wire_ampacity_module.AMPACITY_BY_AWG == wire_ampacity_module._DEFAULT_AMPACITY_BY_AWG


def test_wire_ampacity_failure_does_not_block_the_other_overrides(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    class _RaisingElectricalStore(_FakeStore):
        def dataset(self, key):
            if key.startswith("electrical."):
                raise RuntimeError("boom")
            return super().dataset(key)

    fake = _RaisingElectricalStore(datasets={
        "cost.machine_rates_usd_per_hr": ReferenceDataset(
            key="cost.machine_rates_usd_per_hr", domain="cost",
            entries=[ReferenceEntry(entry_key="fdm_default", value_numeric=13.0)]),
    })
    _patch_store(monkeypatch, fake)

    apply_to_live_app()  # must not raise
    assert cost_module.MACHINE_RATE_USD_PER_HR == 13.0  # unaffected by the electrical-dataset failure
    assert wire_ampacity_module.ampacity_a("AWG10") == 55.0  # fell back to its own default


def test_manufacturing_dfm_failure_does_not_block_the_other_overrides(monkeypatch):
    from packages.catalog.bootstrap import apply_to_live_app

    class _RaisingManufacturingStore(_FakeStore):
        def dataset(self, key):
            if key.startswith("manufacturing."):
                raise RuntimeError("boom")
            return super().dataset(key)

    fake = _RaisingManufacturingStore(datasets={
        "cost.machine_rates_usd_per_hr": ReferenceDataset(
            key="cost.machine_rates_usd_per_hr", domain="cost",
            entries=[ReferenceEntry(entry_key="fdm_default", value_numeric=11.0)]),
    })
    _patch_store(monkeypatch, fake)

    apply_to_live_app()  # must not raise
    assert cost_module.MACHINE_RATE_USD_PER_HR == 11.0  # unaffected by the manufacturing failure
    assert "M3→3.4" in manufacturing_module._fragment()  # manufacturing fell back to its own default
