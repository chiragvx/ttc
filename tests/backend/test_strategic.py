"""Strategic agent: goal -> requirements matrix."""

from __future__ import annotations

from packages.agents.strategic import MockStrategicProvider, StrategicAgent
from packages.ledger.requirements import ReqStatus


def test_goal_becomes_requirements():
    agent = StrategicAgent(MockStrategicProvider())
    matrix = agent.plan("a bracket that holds the load at FS 2, prints under 2 hours, stays under 30 g")
    metrics = {r.metric for r in matrix.requirements}
    assert metrics == {"factor_of_safety", "mass_g", "print_time_s"}
    assert agent.floor_fs(matrix) == 2.0


def test_default_fs_when_unspecified():
    matrix = StrategicAgent().plan("a simple mounting plate")
    fs = [r for r in matrix.requirements if r.metric == "factor_of_safety"]
    assert fs and fs[0].target == 1.5


def test_matrix_evaluates_against_metrics():
    matrix = StrategicAgent().plan("bracket at FS 2, under 30 g")
    # FS met, mass violated
    results = {r.requirement.metric: r.status for r in matrix.evaluate({"factor_of_safety": 4.0, "mass_g": 45.0})}
    assert results["factor_of_safety"] is ReqStatus.SATISFIED
    assert results["mass_g"] is ReqStatus.VIOLATED
