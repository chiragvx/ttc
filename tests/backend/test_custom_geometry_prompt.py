"""Phase 6 (the LAST of 7) of the AI-generated-custom-geometry initiative — prompt_builder.py's own
system-prompt-level framing for the `propose_custom_geometry` tool (Phase 5, already built/wired). The
tool schema's own `description` (custom_geometry_provider.py::custom_geometry_tool_schema /
openrouter_provider.py's inline tool description) already covers the wire-level mechanics; this section
covers what a tool schema's `description` field can't: WHEN to even reach for it relative to the rest of
a turn (catalog + composition first), and the MANDATORY plain-disclosure rule for the chat reply once a
generated part is actually placed. Mirrors `_RESEARCH_TOOL_SECTION`'s own gating shape exactly —
`custom_geometry_enabled()` (packages/agents/custom_geometry_provider.py), same env-var-gated predicate
shape as `research_provider_configured()`, default OFF."""

from __future__ import annotations

from packages.agents.prompt_builder import build_system_prompt
from packages.transport.app import make_demo_ledger


def test_prompt_omits_custom_geometry_section_when_disabled(monkeypatch):
    monkeypatch.delenv("ENABLE_AI_GENERATED_SUBSYSTEMS", raising=False)
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "propose_custom_geometry" not in prompt
    assert "MANDATORY, PLAIN DISCLOSURE" not in prompt


def test_prompt_omits_custom_geometry_section_when_explicitly_off(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_GENERATED_SUBSYSTEMS", "0")
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "propose_custom_geometry" not in prompt


def test_prompt_includes_custom_geometry_section_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_GENERATED_SUBSYSTEMS", "1")
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "propose_custom_geometry" in prompt
    # the mandatory-disclosure rule — the whole point of this phase — must actually be present, not
    # just the tool's name
    assert "MANDATORY, PLAIN DISCLOSURE" in prompt
    assert "AI-generated, unreviewed geometry" in prompt


def test_prompt_custom_geometry_section_tells_the_model_to_check_catalog_and_composition_first(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_GENERATED_SUBSYSTEMS", "1")
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "LAST RESORT" in prompt
    assert "packages/subsystems/compose.py" in prompt


def test_prompt_custom_geometry_section_covers_rejection_handling(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_GENERATED_SUBSYSTEMS", "1")
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "rejection_reason" in prompt


def test_prompt_custom_geometry_section_is_honest_about_fea_eligible(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_GENERATED_SUBSYSTEMS", "1")
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "fea_eligible=False" in prompt


def test_research_section_gating_is_unaffected_by_custom_geometry_gating(monkeypatch):
    # Regression: adding the new gate right next to the existing research gate must not couple the
    # two — each tool's section should appear/disappear independently based on its OWN env var only.
    monkeypatch.delenv("ENABLE_AI_GENERATED_SUBSYSTEMS", raising=False)
    monkeypatch.setenv("RESEARCH_PROVIDER_API_KEY", "x")
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "research_reference" in prompt
    assert "propose_custom_geometry" not in prompt

    monkeypatch.setenv("ENABLE_AI_GENERATED_SUBSYSTEMS", "1")
    prompt2 = build_system_prompt(None, make_demo_ledger())
    assert "research_reference" in prompt2
    assert "propose_custom_geometry" in prompt2
