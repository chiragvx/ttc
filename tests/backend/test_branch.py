"""Invariant-aware 3-way merge of the parametric ledger."""

from __future__ import annotations

from packages.ledger.branch import merge_ledgers

SKIN = "skin_thickness_mm"


def test_non_conflicting_changes_merge_cleanly(base_ledger, pd_factory):
    ours = base_ledger.model_copy(deep=True)
    ours.instances["root"].params["skin_thickness_mm"] = pd_factory(3.0, 1.0, 5.0)
    theirs = base_ledger.model_copy(deep=True)
    theirs.instances["root"].params["internal_rib_spacing_mm"] = pd_factory(25.0, 10.0, 50.0)

    r = merge_ledgers(base_ledger, ours, theirs)
    assert r.clean
    assert r.merged.instances["root"].params["skin_thickness_mm"].value == 3.0
    assert r.merged.instances["root"].params["internal_rib_spacing_mm"].value == 25.0


def test_same_change_on_both_sides_is_clean(base_ledger, pd_factory):
    ours = base_ledger.model_copy(deep=True)
    theirs = base_ledger.model_copy(deep=True)
    for led in (ours, theirs):
        led.instances["root"].params["skin_thickness_mm"] = pd_factory(3.0, 1.0, 5.0)
    r = merge_ledgers(base_ledger, ours, theirs)
    assert r.clean and r.merged.instances["root"].params["skin_thickness_mm"].value == 3.0


def test_divergent_change_is_conflict_and_keeps_base(base_ledger, pd_factory):
    ours = base_ledger.model_copy(deep=True)
    ours.instances["root"].params["skin_thickness_mm"] = pd_factory(3.0, 1.0, 5.0)
    theirs = base_ledger.model_copy(deep=True)
    theirs.instances["root"].params["skin_thickness_mm"] = pd_factory(4.0, 1.0, 5.0)

    r = merge_ledgers(base_ledger, ours, theirs)
    assert not r.clean
    assert any(SKIN in c.path for c in r.conflicts)
    assert r.merged.instances["root"].params["skin_thickness_mm"].value == 2.0  # base, pending resolution


def test_merge_that_breaks_an_invariant_is_a_conflict(ledger_factory, pd_factory):
    base = ledger_factory(skin_bounds=(0.5, 5.0))
    ours = base.model_copy(deep=True)
    ours.instances["root"].params["skin_thickness_mm"] = pd_factory(0.6, 0.5, 5.0)  # in-bounds but < min wall
    r = merge_ledgers(base, ours, base)
    assert not r.clean
    assert any(c.path == "<invariant>" for c in r.conflicts)
