"""REST test for GET /model_capabilities (vision-in-the-loop, 2026-08-05) -- TestClient(create_app()),
mirroring tests/backend/test_region_transport.py's own pattern. The actual capability-lookup LOGIC
(registry fetch, module-level caching/TTL, every failure mode) is unit-tested directly against
`model_supports_vision` in tests/backend/test_openrouter_provider.py -- this file only proves the
route wires its `model` query param through to that function and shapes the JSON response correctly,
without ever hitting the real network (the underlying lookup is monkeypatched)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.transport.app import create_app


def _client():
    return TestClient(create_app())


def test_model_capabilities_missing_model_param_returns_false_not_an_error():
    # a caller with no model configured yet (fresh session, Settings not filled in) is a normal case
    # -- must be a clean {"vision": False}, never a 4xx/5xx.
    c = _client()
    r = c.get("/model_capabilities")
    assert r.status_code == 200
    assert r.json() == {"vision": False}


def test_model_capabilities_empty_model_param_returns_false_not_an_error():
    c = _client()
    r = c.get("/model_capabilities", params={"model": ""})
    assert r.status_code == 200
    assert r.json() == {"vision": False}


def test_model_capabilities_true_for_a_vision_capable_model(monkeypatch):
    monkeypatch.setattr(
        "packages.agents.openrouter_provider.model_supports_vision",
        lambda model, **kw: model == "openai/gpt-5.6-luna",
    )
    c = _client()
    r = c.get("/model_capabilities", params={"model": "openai/gpt-5.6-luna"})
    assert r.status_code == 200
    assert r.json() == {"vision": True}


def test_model_capabilities_false_for_a_text_only_model(monkeypatch):
    monkeypatch.setattr(
        "packages.agents.openrouter_provider.model_supports_vision",
        lambda model, **kw: model == "openai/gpt-5.6-luna",
    )
    c = _client()
    r = c.get("/model_capabilities", params={"model": "deepseek/deepseek-v4-flash"})
    assert r.status_code == 200
    assert r.json() == {"vision": False}
