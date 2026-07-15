"""Strategic agent: goal -> requirements matrix."""

from __future__ import annotations

from packages.agents.strategic import HeuristicStrategicProvider, StrategicAgent
from packages.ledger.requirements import ReqStatus


def test_goal_becomes_requirements():
    agent = StrategicAgent(HeuristicStrategicProvider())
    matrix = agent.plan("a bracket that holds the load at FS 2, prints under 2 hours, stays under 30 g")
    metrics = {r.metric for r in matrix.requirements}
    assert metrics == {"factor_of_safety", "mass_g", "print_time_s"}
    assert agent.floor_fs(matrix) == 2.0


def test_default_fs_when_unspecified():
    matrix = StrategicAgent().plan("a simple mounting plate")
    fs = [r for r in matrix.requirements if r.metric == "factor_of_safety"]
    assert fs and fs[0].target == 1.5


def test_merge_accretes_targets_across_messages():
    agent = StrategicAgent()
    m = agent.plan("a bracket at FS 2")                 # {FS 2}
    m = agent.merge(m, "actually make it under 30 g")    # + mass, FS kept
    metrics = {r.metric: r.target for r in m.requirements}
    assert metrics == {"factor_of_safety": 2.0, "mass_g": 30.0}
    m = agent.merge(m, "bump it to FS 3")                # upsert FS, mass kept
    metrics = {r.metric: r.target for r in m.requirements}
    assert metrics == {"factor_of_safety": 3.0, "mass_g": 30.0}


def test_merge_ignores_messages_with_no_target():
    agent = StrategicAgent()
    m = agent.plan("a bracket at FS 2")
    assert agent.merge(m, "make it look nicer please") is m   # untouched -> ordinary chat won't wipe the goal


def test_matrix_evaluates_against_metrics():
    matrix = StrategicAgent().plan("bracket at FS 2, under 30 g")
    # FS met, mass violated
    results = {r.requirement.metric: r.status for r in matrix.evaluate({"factor_of_safety": 4.0, "mass_g": 45.0})}
    assert results["factor_of_safety"] is ReqStatus.SATISFIED
    assert results["mass_g"] is ReqStatus.VIOLATED


# --- extract_load_n: a stated applied load -> a solver INPUT, not a checkable target -------------

def test_extract_load_n_parses_stated_load():
    agent = StrategicAgent(HeuristicStrategicProvider())
    assert agent.extract_load_n("a bracket that holds 200 N at FS 2") == 200.0
    assert agent.extract_load_n("under a 50N load") == 50.0
    assert agent.extract_load_n("resists 100 newtons") == 100.0


def test_extract_load_n_none_when_unstated():
    agent = StrategicAgent(HeuristicStrategicProvider())
    assert agent.extract_load_n("a simple mounting plate") is None


def test_extract_load_n_no_false_positive_on_unrelated_n_words():
    # "nodes"/"nozzles" must not be mistaken for a Newton unit just because they start with 'n'
    agent = StrategicAgent(HeuristicStrategicProvider())
    assert agent.extract_load_n("a bracket with 20 nodes in the mesh") is None
    assert agent.extract_load_n("needs 12 nozzles") is None


def test_extract_load_n_not_folded_into_the_requirements_matrix():
    # deliberately kept OUT of plan_requirements/VerificationMatrix (see strategic.py's docstring) --
    # a stated load is a solver input, not a pass/fail check against a solved metric.
    matrix = StrategicAgent().plan("a bracket that holds 200 N at FS 2")
    assert "load_n" not in {r.metric for r in matrix.requirements}
