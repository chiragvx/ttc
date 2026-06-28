"""text-to-cad CLI + provider factory (no mock — no key means no LLM)."""

from __future__ import annotations

from packages.agents.provider_factory import get_provider
from packages.cli import main, run_once


def test_run_once_proposes_with_provider(stub_provider):
    _, result = run_once("make the skin 3 mm", provider=stub_provider)
    assert not result.needs_clarification
    assert result.proposal.deltas[0].requested_value == 3.0
    assert result.trial_outcomes[0].status.value == "APPLIED"


def test_run_once_clarifies_on_ambiguous(stub_provider):
    _, result = run_once("make it nicer", provider=stub_provider)
    assert result.needs_clarification


def test_cli_no_key_says_no_llm(capsys, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rc = main(["propose", "make the skin 3 mm"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No LLM configured" in out


def test_cli_status_exits_zero(capsys):
    rc = main(["status"])
    out = capsys.readouterr().out
    assert rc == 0 and "parameters:" in out


def test_provider_factory_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert get_provider() is None


def test_provider_factory_returns_openrouter_with_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    assert isinstance(get_provider(), OpenRouterDeltaProvider)
