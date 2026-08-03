"""Reference research (2026-08-01, tool-call redesign same day): the deterministic pre-turn
heuristic this file originally tested (`_research_query_for`) over-triggered (fired on literally any
first message in an empty file, no model judgment involved) and was replaced with a real
`research_reference` tool the model decides to call — see
`packages/agents/openrouter_provider.py::OpenRouterDeltaProvider.stream_chat`'s docstring for the
bounded multi-round tool loop, and `tests/backend/test_openrouter_provider.py` for its coverage.

This file now only covers the thin `/chat`-level SSE dispatch: a `("research", finding)` tuple
yielded by `stream_chat` must map to the correct `{"type": "research", ...}` SSE frame — the same
"mock stream_chat directly" pattern the original tests here already used."""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.agents.research_provider import ResearchFinding
from packages.transport.app import create_app


def _empty_client() -> TestClient:
    return TestClient(create_app())


def test_chat_dispatches_a_research_event_yielded_by_stream_chat(monkeypatch):
    finding = ResearchFinding(
        query="adjustable laptop stand",
        summary="typical adjustable laptop stands use a riser/hinge mechanism and a platform, not a rigid table",
        suggested_subsystem_types=["hinge", "flat_bar"],
        source_urls=["https://example.com/laptop-stand"],
    )

    def fake_stream_chat(self, *, messages, ledger_json):
        yield "research", finding
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )

    c = _empty_client()
    original = [{"role": "user", "content": "make an adjustable laptop stand"}]
    res = c.post("/chat", json={"messages": original, "api_key": "x"})
    assert res.status_code == 200
    assert '"type": "research"' in res.text
    assert "riser/hinge mechanism" in res.text
    assert "hinge" in res.text and "flat_bar" in res.text


def test_chat_never_yields_research_when_stream_chat_yields_none(monkeypatch):
    # stream_chat itself now owns the decision (via its own tool loop) -- /chat has nothing left to
    # gate; this just confirms the dispatch loop doesn't fabricate an event that was never yielded.
    def fake_stream_chat(self, *, messages, ledger_json):
        yield "done", None

    monkeypatch.setattr(
        "packages.agents.openrouter_provider.OpenRouterDeltaProvider.stream_chat", fake_stream_chat,
    )

    c = _empty_client()
    original = [{"role": "user", "content": "make a laptop stand"}]
    res = c.post("/chat", json={"messages": original, "api_key": "x"})
    assert res.status_code == 200
    assert '"type": "research"' not in res.text
