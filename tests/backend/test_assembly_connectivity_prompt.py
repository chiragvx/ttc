"""Phase 5.5 (2026-07-19) — the "loose kit vs. functional assembly" prompt section. Live bug: the
copilot's own worked examples for the most common multi-part decompositions (satellite/drone frame/
robot arm) taught it to compose parts via bare instance_ops with no connection_ops and no rough-
first-pass caveat — the exact anti-pattern that produced a 6-part "intake manifold" where 5 parts were
floating 6-15mm apart with zero connection between them, silently presented as a finished design."""

from __future__ import annotations

from packages.agents.prompt_builder import build_system_prompt
from packages.transport.app import make_demo_ledger


def test_prompt_teaches_loose_kit_vs_functional_assembly_distinction():
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "functional assembly" in prompt.lower()
    assert "loose kit" in prompt.lower()
    # the actionable rule for the no-interface case — never silently present a scattered auto-layout
    # as if it were a finished, joined assembly
    assert "rough" in prompt.lower() and "first pass" in prompt.lower()


def test_prompt_worked_examples_point_at_the_connectivity_rule():
    # the satellite/drone-frame/robot-arm examples that caused the live bug must reference the new
    # section, not just silently sit next to it
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "design a satellite" in prompt
    assert "FUNCTIONAL-ASSEMBLY decompositions" in prompt
