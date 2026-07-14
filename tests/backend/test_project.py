"""Project/branch service: fork (copy-on-write), divergence, compare, invariant-aware merge."""

from __future__ import annotations

from packages.agents.strategic import StrategicAgent
from packages.ledger.deltas import ParameterDelta
from packages.ledger.project import Project

SKIN = "instances.root.params.skin_thickness_mm"
RIB = "instances.root.params.internal_rib_spacing_mm"
TS = "2026-06-28T00:00:00Z"


def _project(base_ledger) -> Project:
    return Project("demo", base_ledger, ts=TS)


def test_fork_then_diverge_independently(base_ledger):
    proj = _project(base_ledger)
    proj.fork("variant")
    assert proj.branches() == ["main", "variant"]

    proj.mutate("variant", ParameterDelta(target_node=SKIN, requested_value=3.0), actor="ai", ts=TS)
    assert proj.ledger("variant").instances["root"].params["skin_thickness_mm"].value == 3.0
    assert proj.ledger("main").instances["root"].params["skin_thickness_mm"].value == 2.0  # main untouched


def test_merge_non_conflicting_branches(base_ledger):
    proj = _project(base_ledger)
    proj.fork("a")
    proj.fork("b")
    proj.mutate("a", ParameterDelta(target_node=SKIN, requested_value=3.0), actor="ai", ts=TS)
    proj.mutate("b", ParameterDelta(target_node=RIB, requested_value=25.0), actor="ai", ts=TS)

    result = proj.merge(base="main", ours="a", theirs="b")
    assert result.clean
    assert result.merged.instances["root"].params["skin_thickness_mm"].value == 3.0
    assert result.merged.instances["root"].params["internal_rib_spacing_mm"].value == 25.0


def test_merge_conflict_surfaces(base_ledger):
    proj = _project(base_ledger)
    proj.fork("a")
    proj.fork("b")
    proj.mutate("a", ParameterDelta(target_node=SKIN, requested_value=3.0), actor="ai", ts=TS)
    proj.mutate("b", ParameterDelta(target_node=SKIN, requested_value=4.0), actor="ai", ts=TS)
    assert not proj.merge(base="main", ours="a", theirs="b").clean


def test_compare_branches_by_requirements(base_ledger):
    proj = _project(base_ledger)
    proj.fork("strong")
    matrix = StrategicAgent().plan("bracket at FS 2, under 30 g")
    scores = proj.compare(matrix, {
        "main": {"factor_of_safety": 1.2, "mass_g": 20.0},     # FS fails -> 1
        "strong": {"factor_of_safety": 3.0, "mass_g": 25.0},   # both pass -> 2
    })
    assert scores["strong"] > scores["main"]
