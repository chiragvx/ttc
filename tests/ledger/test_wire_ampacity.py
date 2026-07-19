"""packages/ledger/wire_ampacity.py's AWG ampacity catalog override point — the injection seam
packages/catalog/bootstrap.py uses (2026-07-19, mirrors test_bom.py's material catalog tests
exactly). No I/O here (this package's CLAUDE.md forbids it) — these are pure reassignment tests."""

from __future__ import annotations

import pytest

from packages.ledger.wire_ampacity import ampacity_a, reset_wire_ampacity_db, set_wire_ampacity_db


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_wire_ampacity_db()


def test_default_ampacity_for_known_awg_sizes():
    assert ampacity_a("AWG10") == 55.0
    assert ampacity_a("AWG30") == 0.86


def test_ampacity_accepts_a_bare_gauge_number_too():
    assert ampacity_a("10") == ampacity_a("AWG10")
    assert ampacity_a("22") == ampacity_a("AWG22")


def test_set_wire_ampacity_db_overrides_lookups():
    set_wire_ampacity_db({"AWG10": 999.0})
    assert ampacity_a("AWG10") == 999.0


def test_set_wire_ampacity_db_replaces_the_whole_table_not_merges():
    set_wire_ampacity_db({"AWG10": 999.0})
    with pytest.raises(KeyError):
        ampacity_a("AWG22")


def test_set_wire_ampacity_db_with_empty_dict_is_a_noop():
    before = ampacity_a("AWG10")
    set_wire_ampacity_db({})
    assert ampacity_a("AWG10") == before


def test_reset_wire_ampacity_db_restores_the_hardcoded_default():
    original = ampacity_a("AWG10")
    set_wire_ampacity_db({"AWG10": 999.0})
    assert ampacity_a("AWG10") == 999.0

    reset_wire_ampacity_db()
    assert ampacity_a("AWG10") == original


def test_unknown_awg_size_raises_a_helpful_error():
    with pytest.raises(KeyError, match="unknown AWG size"):
        ampacity_a("AWG7")
