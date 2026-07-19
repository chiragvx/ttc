"""2026-07-19 fix: the copilot could never actually propose a material change — deltas.py's
requested_value was float-only AND the prompt's own _CROSS_CUTTING comment said material "isn't
listed here" with no other section covering it either. apply_delta now has a real string-valued-target
branch (test_apply.py); this covers the other half of the fix -- the LLM must actually be TOLD
material_profile is a legal target_node, or the plumbing working underneath doesn't help."""

from __future__ import annotations

from packages.agents.prompt_builder import build_system_prompt
from packages.ledger.bom import MATERIAL_DB
from packages.subsystems import add_instance
from packages.transport.app import make_demo_ledger


def test_prompt_tells_the_copilot_material_is_a_legal_target():
    led = add_instance(make_demo_ledger(), "bracket", "root")
    prompt = build_system_prompt(None, led)
    assert "domains.structure.material_profile" in prompt
    assert "current: PLA" in prompt
    for name in MATERIAL_DB:
        assert name in prompt
    # the actionable instruction: propose it as a STRING, not a number
    assert "as a STRING requested_value" in prompt


def test_prompt_material_section_reflects_the_live_current_value():
    led = add_instance(make_demo_ledger(), "bracket", "root")
    led = led.model_copy(update={
        "domains": led.domains.model_copy(update={
            "structure": led.domains.structure.model_copy(update={"material_profile": "AL6061"})})})
    prompt = build_system_prompt(None, led)
    assert "current: AL6061" in prompt
