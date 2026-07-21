"""Strategic agent: goal -> requirements matrix."""

from __future__ import annotations

from packages.agents.strategic import HeuristicStrategicProvider, StrategicAgent
from packages.ledger.requirements import ReqStatus, VerificationMethod


def test_goal_becomes_requirements():
    agent = StrategicAgent(HeuristicStrategicProvider())
    matrix = agent.plan("a bracket that holds the load at FS 2, prints under 2 hours, stays under 30 g")
    metrics = {r.metric for r in matrix.requirements}
    assert metrics == {"factor_of_safety", "mass_g", "print_time_s"}
    assert agent.floor_fs(matrix) == 2.0


def test_print_time_hours_converts_to_seconds_correctly():
    # mutation-sweep follow-up (2026-07-22): test_goal_becomes_requirements above only asserted the
    # metric *set* is present, never print_time_s's actual numeric target -- undetected mutation:
    # the hours->seconds factor silently became *60 (minutes) instead of *3600 (hours), turning a
    # stated "2 hours" budget into a 120-second gate with zero test coverage.
    matrix = StrategicAgent().plan("a bracket that prints under 2 hours")
    pt = [r for r in matrix.requirements if r.metric == "print_time_s"]
    assert pt and pt[0].target == 7200.0


def test_print_time_requirement_checks_the_correct_direction():
    # mutation-sweep follow-up: a print-time requirement must be SATISFIED when the real print time is
    # UNDER the stated budget and VIOLATED when it's over -- undetected mutation flipped the op from
    # <= to >=, which would report SATISFIED for an over-budget print and VIOLATED for an on-budget
    # one (a backwards acceptance gate, the exact "fabricated green light" shape this codebase's own
    # guardrails call out).
    matrix = StrategicAgent().plan("a bracket that prints under 2 hours")  # budget: 7200s
    under_budget = {r.requirement.metric: r.status for r in matrix.evaluate({"print_time_s": 5000.0})}
    over_budget = {r.requirement.metric: r.status for r in matrix.evaluate({"print_time_s": 10000.0})}
    assert under_budget["print_time_s"] is ReqStatus.SATISFIED
    assert over_budget["print_time_s"] is ReqStatus.VIOLATED


def test_mass_requirement_uses_test_verification_method():
    # mutation-sweep follow-up: mass is verified by a physical scale measurement (TEST), a real
    # systems-engineering distinction from ANALYSIS (a computed/estimated value) -- undetected
    # mutation silently swapped it to ANALYSIS with zero test ever reading Requirement.method.
    matrix = StrategicAgent().plan("a bracket that stays under 30 g")
    mass = [r for r in matrix.requirements if r.metric == "mass_g"]
    assert mass and mass[0].method is VerificationMethod.TEST


def test_merge_keeps_the_one_based_requirement_id_convention():
    # mutation-sweep follow-up: plan() numbers requirements R1, R2, ... -- merge() must keep the SAME
    # convention after upserting, not drift to a 0-based R0, R1, ... (an undetected off-by-one; ids
    # stayed unique so nothing crashed, but the id scheme silently diverged from plan()'s own).
    agent = StrategicAgent()
    m = agent.plan("a bracket at FS 2")
    m = agent.merge(m, "under 30 g")
    assert sorted(r.id for r in m.requirements) == ["R1", "R2"]


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
