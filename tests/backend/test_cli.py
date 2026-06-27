"""text-to-cad CLI + provider factory."""

from __future__ import annotations

from packages.agents.mock_provider import MockProvider
from packages.agents.provider_factory import get_provider
from packages.cli import main, run_once


def test_run_once_proposes_with_mock():
    _, result = run_once("make the skin 3 mm", provider=MockProvider())
    assert not result.needs_clarification
    assert result.proposal.deltas[0].requested_value == 3.0
    assert result.trial_outcomes[0].status.value == "APPLIED"


def test_run_once_clarifies_on_ambiguous():
    _, result = run_once("make it stronger", provider=MockProvider())
    assert result.needs_clarification


def test_cli_propose_prints_and_exits_zero(capsys):
    rc = main(["propose", "make the skin 3 mm"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "proposed" in out
    assert "EXPORT_BLOCKED" in out  # nothing exportable until grounded FS + sign-off


def test_cli_status_exits_zero(capsys):
    rc = main(["status"])
    out = capsys.readouterr().out
    assert rc == 0 and "parameters:" in out


def test_provider_factory_defaults_to_mock_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert isinstance(get_provider(), MockProvider)
