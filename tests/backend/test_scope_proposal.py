"""ScopeSpec (Phase 5): `ScopePartProposal`/`ScopeProposal` (packages/ledger/deltas.py) and the new
`DeltaProposal.scope_proposal` field — a structured part-manifest SUMMARY for a big/ambiguous
multi-part ask ('make a drone'). Pure DISPLAY data: no `op`, no apply step, no outcome. Mirrors
tests/couplings/test_couplings.py's `ValidationError` style for extra="forbid" coverage and
tests/backend/test_app.py's `test_chat_proposal_includes_feature_ops`/`_instance_ops` style for the
/chat SSE threading (there is no existing connection_ops/coupling_ops SSE test to mirror — those two
ops don't have one yet — so this mirrors the feature_ops/instance_ops SSE tests instead, which do)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from packages.ledger.deltas import DeltaProposal, ScopePartProposal, ScopeProposal
from packages.transport.app import create_app


def _client():
    # a project starts as an empty workspace (2026-07-04) — bootstrap the bracket root every other
    # test in this repo's /chat coverage relies on.
    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    return c


def _drone_manifest() -> ScopeProposal:
    return ScopeProposal(
        goal="make a small quadcopter frame",
        parts=[
            ScopePartProposal(subsystem_type="standoff_frame", role="center frame", count=1,
                               operating_conditions=["carries battery + FC stack"],
                               rationale="central structural hub for the 4 arms"),
            ScopePartProposal(subsystem_type="standoff", role="motor arm", count=4,
                               operating_conditions=["cantilevered motor thrust load"]),
            ScopePartProposal(subsystem_type="enclosure", role="battery bay", count=1,
                               operating_conditions=["holds a 4S LiPo"],
                               rationale="protects the battery from prop wash debris"),
        ],
        out_of_scope=["propulsion sizing", "flight controller firmware", "aerodynamics"],
        open_questions=["arm length target?", "battery capacity?"],
    )


# --- 1. ScopeProposal/ScopePartProposal pydantic validation --------------------------------------


def test_scope_part_proposal_round_trips_through_dump_and_validate():
    part = ScopePartProposal(subsystem_type="standoff", role="motor arm", count=4,
                              operating_conditions=["cantilevered motor thrust load"],
                              rationale="one per motor")
    dumped = part.model_dump()
    restored = ScopePartProposal.model_validate(dumped)
    assert restored == part
    assert dumped["subsystem_type"] == "standoff"
    assert dumped["role"] == "motor arm"
    assert dumped["count"] == 4
    assert dumped["operating_conditions"] == ["cantilevered motor thrust load"]
    assert dumped["rationale"] == "one per motor"


def test_scope_proposal_round_trips_through_dump_and_validate():
    proposal = _drone_manifest()
    dumped = proposal.model_dump()
    restored = ScopeProposal.model_validate(dumped)
    assert restored == proposal
    assert dumped["goal"] == "make a small quadcopter frame"
    assert len(dumped["parts"]) == 3
    assert dumped["parts"][0]["subsystem_type"] == "standoff_frame"
    assert dumped["out_of_scope"] == ["propulsion sizing", "flight controller firmware", "aerodynamics"]
    assert dumped["open_questions"] == ["arm length target?", "battery capacity?"]


def test_scope_part_proposal_defaults_count_and_lists():
    # count defaults to 1; operating_conditions defaults to an empty list; rationale is optional
    part = ScopePartProposal(subsystem_type="bracket", role="mount")
    assert part.count == 1
    assert part.operating_conditions == []
    assert part.rationale is None


def test_scope_part_proposal_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ScopePartProposal(subsystem_type="standoff", role="motor arm", bogus_field="nope")


def test_scope_proposal_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ScopeProposal(goal="make a drone", bogus_field="nope")


# --- 2. DeltaProposal composes cleanly with scope_proposal ----------------------------------------


def test_delta_proposal_with_only_scope_proposal_round_trips():
    proposal = DeltaProposal(scope_proposal=_drone_manifest())
    assert proposal.deltas == []
    assert proposal.instance_ops == []

    dumped = proposal.model_dump()
    assert dumped["scope_proposal"]["goal"] == "make a small quadcopter frame"
    assert dumped["deltas"] == []
    assert dumped["instance_ops"] == []

    restored = DeltaProposal.model_validate(dumped)
    assert restored == proposal
    assert restored.scope_proposal.parts[1].role == "motor arm"


def test_delta_proposal_scope_proposal_defaults_to_none():
    proposal = DeltaProposal()
    assert proposal.scope_proposal is None
    assert proposal.model_dump()["scope_proposal"] is None


# --- 3. /chat SSE threading: scope_proposal reaches the `proposal` event --------------------------


def test_chat_proposal_includes_scope_proposal(monkeypatch):
    """The /chat SSE `proposal` event must carry `scope_proposal` alongside `deltas`/`feature_ops`/
    `instance_ops`/`connection_ops`/`coupling_ops`, serialized the same way
    (`payload.scope_proposal.model_dump(mode="json")`) — see packages/transport/app.py's `/chat`."""
    from packages.ledger.deltas import InstanceOp

    def fake_stream_chat(self, *, messages, ledger_json):
        yield "proposal", DeltaProposal(
            instance_ops=[InstanceOp(op="add_instance", subsystem_type="standoff_frame")],
            scope_proposal=_drone_manifest(),
        )
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )
    res = _client().post("/chat", json={"messages": [{"role": "user", "content": "make a drone"}], "api_key": "x"})
    assert res.status_code == 200
    assert '"type": "proposal"' in res.text
    assert '"scope_proposal"' in res.text
    assert '"goal": "make a small quadcopter frame"' in res.text
    assert '"subsystem_type": "standoff_frame"' in res.text
    assert '"role": "motor arm"' in res.text
    assert '"out_of_scope"' in res.text


def test_chat_proposal_scope_proposal_none_is_explicit_null_not_omitted(monkeypatch):
    """When the LLM doesn't emit a scope_proposal, app.py's `... if payload.scope_proposal else None`
    must still produce an explicit `"scope_proposal": null` key in the SSE event JSON — not omit the
    key, and not crash. Read app.py's actual code before assuming which behavior it has."""
    def fake_stream_chat(self, *, messages, ledger_json):
        yield "proposal", DeltaProposal(feature_ops=[])
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )
    res = _client().post("/chat", json={"messages": [{"role": "user", "content": "add a hole"}], "api_key": "x"})
    assert res.status_code == 200
    assert '"type": "proposal"' in res.text
    assert '"scope_proposal": null' in res.text


# --- 4. The system prompt teaches scope_proposal ---------------------------------------------------


def test_prompt_teaches_scope_proposal_as_additive_not_a_gate():
    from packages.agents.prompt_builder import build_system_prompt
    from packages.transport.app import make_demo_ledger

    prompt = build_system_prompt(None, make_demo_ledger())
    assert "scope_proposal" in prompt

    # policy check (packages/agents/CLAUDE.md, 2026-07-04): a proposal auto-applies through the
    # rules-validated path the instant it arrives; Undo is the safety net, not a pre-apply
    # confirmation click. scope_proposal must NOT be described as a required gate that blocks
    # instance_ops from firing in the confident case.
    assert "not a gate" in prompt.lower() or "not an approval gate" in prompt.lower()
    lowered = prompt.lower()
    assert "no apply step" in lowered or "additive" in lowered
