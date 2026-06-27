"""Runtime agent layer: mock provider, propose->review->commit session, eval harness."""

from __future__ import annotations

from packages.agents.eval import grade
from packages.agents.mock_provider import SKIN, MockProvider
from packages.agents.runtime import CoModelingSession
from packages.ledger.events import EventLog
from packages.ledger.schema import ReviewState

TS = "2026-06-28T00:00:00Z"


def test_mock_provider_maps_intent_and_clarifies():
    p = MockProvider()
    good = p.propose_delta(system="", conversation=[{"role": "user", "content": "make the skin 3 mm"}], ledger_json="{}")
    assert [(d.target_node, d.requested_value) for d in good.deltas] == [(SKIN, 3.0)]
    assert good.request_clarification is None

    amb = p.propose_delta(system="", conversation=[{"role": "user", "content": "make it stronger"}], ledger_json="{}")
    assert amb.request_clarification is not None and not amb.deltas


def test_session_proposes_then_human_commits(base_ledger):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    session = CoModelingSession(MockProvider(), log)

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


def test_clarification_proposal_commits_nothing(base_ledger):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    session = CoModelingSession(MockProvider(), log)
    result = session.propose("make it stronger", ts=TS)
    assert result.needs_clarification
    assert not result.proposal.deltas


def test_eval_harness_golden_is_perfect():
    report = grade(MockProvider())
    assert report.accuracy == 1.0, report.failures
    assert report.clarification_precision == 1.0
