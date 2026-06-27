"""Event-sourced ledger: hash chain, pure-fold replay, derivations don't affect replay state."""

from __future__ import annotations

from packages.ledger.deltas import ParameterDelta
from packages.ledger.events import EventLog
from packages.ledger.schema import ReviewState

SKIN = "domains.structure.skin_thickness_mm"
TS = "2026-06-28T00:00:00Z"


def _log_with_history(base_ledger) -> EventLog:
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_nl_intent("make the skin a bit thicker", actor="user", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.5), actor="ai", ts=TS)
    log.append_signoff(reviewer="pe@example.com", ts=TS)
    return log


def test_fold_reconstructs_state(base_ledger):
    led = _log_with_history(base_ledger).fold()
    assert led.domains.structure.skin_thickness_mm.value == 3.5
    assert led.review.state is ReviewState.ENGINEER_REVIEWED
    assert led.review.reviewer == "pe@example.com"


def test_fold_is_deterministic(base_ledger):
    log = _log_with_history(base_ledger)
    assert log.fold().model_dump() == log.fold().model_dump()


def test_hash_chain_verifies(base_ledger):
    log = _log_with_history(base_ledger)
    assert log.verify_chain() is True


def test_tampering_breaks_the_chain(base_ledger):
    log = _log_with_history(base_ledger)
    log.events()[2].payload["delta"]["requested_value"] = 99.0  # tamper with a recorded fact
    assert log.verify_chain() is False


def test_derivations_do_not_affect_replay_state(base_ledger):
    log = _log_with_history(base_ledger)
    before = log.fold().model_dump()
    # a stored solver artifact must NOT change replay state (rehydrated by hash, never folded)
    ev = log.append_derivation("fs_verdict", b'{"factor_of_safety": 4.05}', fingerprint="fp123",
                               actor="solver", ts=TS)
    after = log.fold().model_dump()
    assert before == after
    assert after["derived"]["factor_of_safety"] is None  # replay never trusts a derivation as state
    assert log.get_artifact(ev.payload["sha256"]) == b'{"factor_of_safety": 4.05}'
