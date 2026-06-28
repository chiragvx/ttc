"""Runtime agent layer: propose->review->commit session + eval harness (test-only stub provider)."""

from __future__ import annotations

from packages.agents.eval import CLARIFY, EvalCase, grade
from packages.agents.runtime import CoModelingSession
from packages.ledger.events import EventLog
from packages.ledger.nodes import SKIN
from packages.ledger.schema import ReviewState

TS = "2026-06-28T00:00:00Z"


def test_session_proposes_then_human_commits(base_ledger, stub_provider):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    session = CoModelingSession(stub_provider, log)

    result = session.propose("make the skin 3 mm", ts=TS)
    assert not result.needs_clarification
    assert result.trial_outcomes[0].status.value == "APPLIED"
    # proposal is NOT yet committed -> fold still shows the original value
    assert log.fold().domains.structure.skin_thickness_mm.value == 2.0

    session.accept(result.proposal.deltas[0], ts=TS)            # human accepts
    assert log.fold().domains.structure.skin_thickness_mm.value == 3.0
    assert log.fold().review.state is ReviewState.AI_PROPOSED   # still needs sign-off

    session.signoff("pe@example.com", ts=TS)
    assert log.fold().review.state is ReviewState.ENGINEER_REVIEWED


def test_clarification_proposal_commits_nothing(base_ledger, stub_provider):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    session = CoModelingSession(stub_provider, log)
    result = session.propose("make it better somehow", ts=TS)
    assert result.needs_clarification
    assert not result.proposal.deltas
    assert SKIN  # node constant import sanity


def test_eval_harness_computes_metrics(stub_provider):
    cases = [
        EvalCase("make the skin 3 mm", [(SKIN, 3.0)]),     # stub correct
        EvalCase("make it stronger", CLARIFY),             # stub clarifies (correct)
        EvalCase("make the skin 3 mm", [(SKIN, 99.0)]),    # stub returns 3.0 -> WRONG
    ]
    report = grade(stub_provider, cases)
    assert report.total == 3 and report.passed == 2       # one mismatch detected
    assert report.clarified == 1 and report.clarification_precision == 1.0
