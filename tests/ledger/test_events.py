"""Event-sourced ledger: hash chain, pure-fold replay, derivations don't affect replay state."""

from __future__ import annotations

import pytest

from packages.ledger.deltas import ParameterDelta
from packages.ledger.events import Event, EventLog
from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import Instance, ReviewState, Transform

SKIN = "instances.root.params.skin_thickness_mm"
TS = "2026-06-28T00:00:00Z"


def _make_instance(instance_id: str = "wing_left") -> Instance:
    return Instance(
        id=instance_id,
        subsystem_type="bracket",
        params={"skin_thickness_mm": ParameterDef(value=2.5, unit="mm", bounds=(1.0, 5.0),
                                                    lock_state=LockState.DYNAMIC)},
        parent_id="root",
    )


def _log_with_history(base_ledger) -> EventLog:
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_nl_intent("make the skin a bit thicker", actor="user", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.5), actor="ai", ts=TS)
    log.append_signoff(reviewer="pe@example.com", ts=TS)
    return log


def test_fold_reconstructs_state(base_ledger):
    led = _log_with_history(base_ledger).fold()
    assert led.instances["root"].params["skin_thickness_mm"].value == 3.5
    assert led.review.state is ReviewState.ENGINEER_REVIEWED
    assert led.review.reviewer == "pe@example.com"


def test_fold_is_deterministic(base_ledger):
    log = _log_with_history(base_ledger)
    assert log.fold().model_dump() == log.fold().model_dump()


def test_signoff_does_not_survive_a_later_mutation(base_ledger):
    """Review.__doc__: 'Geometry-class changes start AI_PROPOSED' — a sign-off must not silently
    cover every later param change forever. A mutation AFTER sign-off resets review back to
    AI_PROPOSED (and clears the stale reviewer); one that changed nothing (never appended as a fact
    in the live app) must not have reset anything either, but that's exercised at the API layer."""
    log = _log_with_history(base_ledger)  # ends signed-off
    assert log.fold().review.state is ReviewState.ENGINEER_REVIEWED

    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=4.0), actor="user", ts=TS)
    led = log.fold()
    assert led.review.state is ReviewState.AI_PROPOSED
    assert led.review.reviewer is None
    assert led.instances["root"].params["skin_thickness_mm"].value == 4.0  # the mutation still applied


def test_signoff_does_not_survive_a_later_instance_add(base_ledger):
    log = _log_with_history(base_ledger)
    assert log.fold().review.state is ReviewState.ENGINEER_REVIEWED

    log.append_instance_added(_make_instance("leg1"), actor="user", ts=TS)
    assert log.fold().review.state is ReviewState.AI_PROPOSED


def test_a_later_signoff_still_applies_after_reset(base_ledger):
    """A reset isn't a one-way ratchet -- a fresh sign-off after the invalidating change still
    moves review to ENGINEER_REVIEWED again."""
    log = _log_with_history(base_ledger)  # ends signed-off at 3.5mm
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=4.0), actor="user", ts=TS)
    assert log.fold().review.state is ReviewState.AI_PROPOSED

    log.append_signoff(reviewer="pe2@example.com", ts=TS)
    led = log.fold()
    assert led.review.state is ReviewState.ENGINEER_REVIEWED
    assert led.review.reviewer == "pe2@example.com"


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


def test_instance_added_is_incremental_history(base_ledger):
    """The point of the feature: adding an instance must NOT wipe prior mutation history. Both the
    earlier PARAMETER_MUTATION and the later INSTANCE_ADDED must survive a single fold()."""
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.5), actor="ai", ts=TS)
    new_instance = _make_instance("wing_left")
    log.append_instance_added(new_instance, actor="ai", ts=TS)

    led = log.fold()

    # prior history survived
    assert led.instances["root"].params["skin_thickness_mm"].value == 3.5
    # the new instance is present with the right identity/type/params
    assert "wing_left" in led.instances
    added = led.instances["wing_left"]
    assert added.subsystem_type == "bracket"
    assert added.parent_id == "root"
    assert added.params["skin_thickness_mm"].value == 2.5
    # root instance untouched aside from the mutation above
    assert led.instances["root"].id == "root"


def test_instance_removed_is_incremental_history(base_ledger):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    new_instance = _make_instance("wing_left")
    log.append_instance_added(new_instance, actor="ai", ts=TS)
    log.append_instance_removed("wing_left", actor="ai", ts=TS)

    led = log.fold()

    assert "wing_left" not in led.instances
    # everything else unchanged
    assert led.instances["root"].params["skin_thickness_mm"].value == 2.0
    assert led.review.state == base_ledger.review.state


def test_verify_chain_holds_across_instance_events(base_ledger):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.5), actor="ai", ts=TS)
    log.append_instance_added(_make_instance("wing_left"), actor="ai", ts=TS)
    log.append_signoff(reviewer="pe@example.com", ts=TS)
    log.append_instance_removed("wing_left", actor="ai", ts=TS)

    assert log.verify_chain() is True
    # sanity: the removal is really reflected after a full replay too
    assert "wing_left" not in log.fold().instances


def test_instance_event_payloads_round_trip_through_strict_event_model(base_ledger):
    """Event has extra='forbid'; confirm the chosen payload shapes survive a model_dump/model_validate
    round trip untouched (no silent field loss, no extra-field rejection)."""
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    added_ev = log.append_instance_added(_make_instance("wing_left"), actor="ai", ts=TS)
    removed_ev = log.append_instance_removed("wing_left", actor="ai", ts=TS)

    for ev in (added_ev, removed_ev):
        round_tripped = Event.model_validate(ev.model_dump())
        assert round_tripped == ev
        round_tripped_json = Event.model_validate_json(ev.model_dump_json())
        assert round_tripped_json == ev

    assert added_ev.payload["instance"]["id"] == "wing_left"
    assert removed_ev.payload == {"instance_id": "wing_left"}


# --- INSTANCE_MOVED: the move_instance fact + its replay branch ---------------------------------
#
# THE CONFIRMED BUG this covers: a live test showed the copilot correctly wanting to reposition an
# ALREADY-PLACED instance ("move the pod on top of the wing") with no legal way to say that in the
# schema. This is the real event-sourced/replayable proof — not just an in-memory mutation.


def test_instance_moved_replay_reconstructs_new_transform_from_scratch(base_ledger):
    """Build an EventLog, append_genesis with an instance already placed at a known non-zero
    transform (position AND rotation), append_instance_moved to a NEW transform, fold()/replay the
    events from scratch, and assert the final ledger's instance transform matches the NEW transform
    exactly — proves this is genuinely event-sourced/replayable, not an in-memory mutation."""
    original_transform = Transform(x_mm=1.0, y_mm=2.0, z_mm=3.0, rx_deg=10.0, ry_deg=20.0, rz_deg=30.0)
    placed_instance = Instance(
        id="pod", subsystem_type="bracket", params={}, parent_id=None, transform=original_transform,
    )
    genesis_ledger = base_ledger.model_copy(
        update={"instances": {**base_ledger.instances, "pod": placed_instance}}
    )

    log = EventLog()
    log.append_genesis(genesis_ledger, actor="system", ts=TS)

    new_transform = Transform(x_mm=100.0, y_mm=200.0, z_mm=300.0, rx_deg=0.0, ry_deg=0.0, rz_deg=0.0)
    log.append_instance_moved("pod", new_transform, actor="ai", ts=TS)

    replayed = log.fold()  # a from-scratch replay over the raw fact log alone

    assert replayed.instances["pod"].transform == new_transform
    # everything else survived untouched
    assert replayed.instances["root"].params["skin_thickness_mm"].value == 2.0


def test_instance_moved_is_incremental_history(base_ledger):
    """Adding/moving must not wipe prior mutation history — mirrors
    test_instance_added_is_incremental_history's pattern for the new fact kind."""
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_mutation(ParameterDelta(target_node=SKIN, requested_value=3.5), actor="ai", ts=TS)
    log.append_instance_added(_make_instance("wing_left"), actor="ai", ts=TS)
    new_transform = Transform(x_mm=5.0, y_mm=6.0, z_mm=7.0)
    log.append_instance_moved("wing_left", new_transform, actor="ai", ts=TS)

    led = log.fold()

    assert led.instances["root"].params["skin_thickness_mm"].value == 3.5  # prior history survived
    assert led.instances["wing_left"].transform == new_transform


def test_instance_moved_on_nonexistent_instance_silently_noops(base_ledger):
    """Mirrors the FEATURE_OP replay branch's documented tolerance for an assembly-template child not
    yet reconciled at this point in the fold: an INSTANCE_MOVED fact targeting an instance_id that
    doesn't (yet) exist in the pure-FACT ledger must NOT raise — it's silently dropped, matching
    NL_INTENT/USAGE's "recorded, not always state-changing" precedent."""
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_instance_moved("ghost", Transform(x_mm=1.0, y_mm=1.0, z_mm=1.0), actor="ai", ts=TS)

    led = log.fold()  # must not raise
    assert "ghost" not in led.instances
    assert led.instances["root"].params["skin_thickness_mm"].value == 2.0


def test_verify_chain_holds_across_instance_moved_events(base_ledger):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_instance_added(_make_instance("wing_left"), actor="ai", ts=TS)
    log.append_instance_moved("wing_left", Transform(x_mm=9.0, y_mm=8.0, z_mm=7.0), actor="ai", ts=TS)

    assert log.verify_chain() is True
    assert log.fold().instances["wing_left"].transform.x_mm == pytest.approx(9.0)


def test_instance_moved_payload_round_trips_through_strict_event_model(base_ledger):
    """Event has extra='forbid'; confirm the INSTANCE_MOVED payload shape survives a
    model_dump/model_validate round trip untouched."""
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    log.append_instance_added(_make_instance("wing_left"), actor="ai", ts=TS)
    moved_ev = log.append_instance_moved(
        "wing_left", Transform(x_mm=1.0, y_mm=2.0, z_mm=3.0), actor="ai", ts=TS)

    round_tripped = Event.model_validate(moved_ev.model_dump())
    assert round_tripped == moved_ev
    round_tripped_json = Event.model_validate_json(moved_ev.model_dump_json())
    assert round_tripped_json == moved_ev

    assert moved_ev.payload["instance_id"] == "wing_left"
    assert moved_ev.payload["transform"]["x_mm"] == 1.0
