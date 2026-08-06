"""2026-08-05 cascade-recovery + requirements-completeness fix (prompt-guidance half). Live repro
(conversation-2026-08-04T20-34-05-002Z.md): a 2-stage gearbox self-check ended on "ok" after 2
auto-correction rounds, but getting there (a) repeated the SAME move_instance-on-every-anchor "fix"
that had already failed once, then (b) remove_instance+add_instance'd its way to a clean check while
silently cascade-dropping 4 gear-ratio couplings and a wiring keep-out region, and (c) never answered
the user's original "give me the exact output RPM and torque" / "confirm the real FS on the output
shaft" asks in any reply, including the final one. This covers the prompt teaches: prefer
`clear_transform` over move_instance/remove+add for the multi-anchor finding, check
`removed_coupling_ids` (and siblings) on every remove_instance/remove_connection response, and
reconfirm the original request's explicit asks before ending a correction turn."""

from __future__ import annotations

from packages.agents.prompt_builder import build_system_prompt
from packages.transport.app import make_demo_ledger


def test_prompt_teaches_clear_transform_for_multi_anchor_finding():
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "clear_transform" in prompt
    assert "can only honor one" in prompt
    # the two confirmed-failed alternatives must be named as failures, not left implicit
    assert "move_instance" in prompt


def test_prompt_teaches_checking_cascade_removed_ids():
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "removed_coupling_ids" in prompt
    assert "removed_region_ids" in prompt
    assert "removed_connection_ids" in prompt


def test_prompt_teaches_reconfirming_the_original_request():
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "reconfirm the" in prompt.lower()
    assert "original" in prompt.lower()
    # the concrete unanswered asks from the live repro, cited so the rule isn't abstract
    assert "output RPM and torque" in prompt
