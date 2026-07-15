"""packages/ledger/bom.py's material catalog override point — the injection seam
packages/catalog/bootstrap.py uses (2026-07-15). No I/O here (this package's CLAUDE.md forbids it) —
these are pure reassignment tests."""

from __future__ import annotations

import pytest

from packages.ledger.bom import Material, material, reset_material_db, set_material_db


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_material_db()


def test_set_material_db_overrides_lookups():
    fake = Material(name="PLA", density_g_per_mm3=9.99, youngs_mod_mpa=1.0, poisson=0.3,
                    yield_mpa=1.0, service_temp_c=1.0, cost_per_kg_usd=1.0)
    set_material_db({"PLA": fake})
    assert material("PLA").density_g_per_mm3 == 9.99


def test_set_material_db_replaces_the_whole_catalog_not_merges():
    """An override with only ONE material means every OTHER material (e.g. STEEL) is gone — this is
    a full replacement, not a merge, matching a real catalog reseed."""
    fake = Material(name="PLA", density_g_per_mm3=9.99, youngs_mod_mpa=1.0, poisson=0.3,
                    yield_mpa=1.0, service_temp_c=1.0, cost_per_kg_usd=1.0)
    set_material_db({"PLA": fake})
    with pytest.raises(KeyError):
        material("STEEL")


def test_set_material_db_with_empty_dict_is_a_noop():
    before = material("PLA")
    set_material_db({})
    assert material("PLA") == before


def test_reset_material_db_restores_the_hardcoded_default():
    original = material("PLA")
    fake = Material(name="PLA", density_g_per_mm3=9.99, youngs_mod_mpa=1.0, poisson=0.3,
                    yield_mpa=1.0, service_temp_c=1.0, cost_per_kg_usd=1.0)
    set_material_db({"PLA": fake})
    assert material("PLA").density_g_per_mm3 == 9.99

    reset_material_db()
    assert material("PLA") == original


def test_unknown_material_still_raises_a_helpful_error():
    with pytest.raises(KeyError, match="unknown material"):
        material("UNOBTAINIUM")
