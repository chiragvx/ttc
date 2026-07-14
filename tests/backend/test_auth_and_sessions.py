"""Session isolation + auth (2026-07-15): one global SessionState used to be shared by every client
that ever hit this server, and every endpoint was unauthenticated. Now each browser session gets its
own isolated SessionState (keyed by an opaque cookie), and an operator-configured AUTH_TOKEN gates
who can ever mint a new one — see packages/transport/app.py's SessionManager/_require_session."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDisconnect

from packages.transport.app import create_app

SKIN = "instances.root.params.skin_thickness_mm"


def _bootstrap(c: TestClient, **headers) -> None:
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"}, headers=headers)


# --- session isolation (no AUTH_TOKEN configured — today's default) ---------------------------------


def test_two_clients_get_isolated_sessions_not_one_shared_global():
    app = create_app()
    c1 = TestClient(app)
    c2 = TestClient(app)
    _bootstrap(c1)
    _bootstrap(c2)

    with c1.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 9.0})
        ws.receive_json()

    # c1's mutation must NOT be visible to c2 — before this fix, both clients shared ONE SessionState
    # and this would have been 9.0 for both.
    assert c1.get("/ledger").json()["instances"]["root"]["params"]["skin_thickness_mm"]["value"] == 9.0
    assert c2.get("/ledger").json()["instances"]["root"]["params"]["skin_thickness_mm"]["value"] == 2.0


def test_two_clients_get_independent_file_sets():
    app = create_app()
    c1 = TestClient(app)
    c2 = TestClient(app)
    _bootstrap(c1)
    _bootstrap(c2)

    c1.post("/files")  # c1 now has 2 files; c2 must still have exactly its own 1
    assert len(c1.get("/files").json()["files"]) == 2
    assert len(c2.get("/files").json()["files"]) == 1


def test_no_auth_token_configured_every_request_is_open(monkeypatch):
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    c = TestClient(create_app())
    res = c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    assert res.status_code == 200
    assert res.json()["ok"] is True


# --- AUTH_TOKEN gating --------------------------------------------------------------------------


def test_healthz_bypasses_auth_even_when_token_configured(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    assert c.get("/healthz").json() == {"ok": True}
    assert "gtc_session" not in c.cookies  # /healthz never touches session/auth machinery at all


def test_request_with_no_token_is_rejected_when_configured(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    res = c.get("/ledger")
    assert res.status_code == 401


def test_request_with_wrong_token_is_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    res = c.get("/ledger", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401


def test_correct_token_mints_a_session_and_cookie_covers_later_requests(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    res = c.get("/ledger", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200
    assert "gtc_session" in c.cookies

    # the SAME client, cookie now set, no header needed on a later request
    res2 = c.get("/ledger")
    assert res2.status_code == 200


def test_a_second_client_without_the_token_cannot_piggyback(monkeypatch):
    """The cookie is per-browser — a second client with no cookie and no token still gets 401, even
    though a first (correctly-authenticated) client already exists on the same server."""
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    app = create_app()
    c1 = TestClient(app)
    c1.get("/ledger", headers={"Authorization": "Bearer s3cret"})  # c1 is now authenticated

    c2 = TestClient(app)
    assert c2.get("/ledger").status_code == 401


def test_malformed_authorization_header_is_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    res = c.get("/ledger", headers={"Authorization": "s3cret"})  # missing "Bearer " prefix
    assert res.status_code == 401


def test_chat_and_propose_are_gated_too(monkeypatch):
    """These are the LLM-budget-spend vector: without this gate, any anonymous network caller could
    hit /propose or /chat and (per packages/agents/provider_factory.py's fallback) spend the
    operator's own OPENROUTER_API_KEY. Confirms both endpoints sit behind the same auth dependency
    as everything else — no separate carve-out was accidentally left open."""
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    assert c.post("/propose", json={"intent": "make it bigger"}).status_code == 401
    assert c.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 401


def test_openapi_docs_and_redoc_are_gated_too(monkeypatch):
    """2026-07-15 audit finding: FastAPI's implicit /docs, /redoc, /openapi.json routes are registered
    directly on the app at construction time, BEFORE the router's auth dependency exists — they were
    never wrapped by it, leaking the full private route/schema surface (including internal request
    fields like ProposeRequest.api_key) to anyone, even with AUTH_TOKEN configured. Now disabled by
    default and re-implemented ON the router so they inherit the same gate."""
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    assert c.get("/openapi.json").status_code == 401
    assert c.get("/docs").status_code == 401
    assert c.get("/redoc").status_code == 401
    assert "gtc_session" not in c.cookies  # none of the three ever minted a session

    # and they DO work once actually authenticated, proving this isn't just a blanket 404
    res = c.get("/openapi.json", headers={"Authorization": "Bearer s3cret"})
    assert res.status_code == 200
    assert "/ledger" in res.json()["paths"]


def test_session_limit_rejects_new_sessions_instead_of_evicting_live_ones(monkeypatch):
    """2026-07-15 audit finding: the original FIFO eviction policy let ANY unauthenticated caller
    (the default when AUTH_TOKEN is unset) silently wipe out another user's live in-memory design by
    spamming session-minting requests until the victim's session aged out. Reaching the cap must
    refuse NEW sessions (503) instead, leaving every existing session untouched."""
    from packages.transport.app import SessionManager

    monkeypatch.setattr(SessionManager, "MAX_SESSIONS", 2)
    app = create_app()

    victim = TestClient(app)
    _bootstrap(victim)
    victim_cookie = victim.cookies.get("gtc_session")
    assert victim_cookie is not None

    filler = TestClient(app)
    filler.get("/files")  # session #2 -- fills the cap (MAX_SESSIONS=2)

    attacker = TestClient(app)
    res = attacker.get("/files")  # would-be session #3 -- must be refused, not evict the victim
    assert res.status_code == 503

    # the victim's original session is completely untouched
    assert victim.get("/ledger").json()["instances"]["root"]["params"]["skin_thickness_mm"]["value"] == 2.0
    assert victim.cookies.get("gtc_session") == victim_cookie


# --- WS auth -------------------------------------------------------------------------------------


def test_ws_connect_without_auth_is_refused_when_token_configured(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws"):
            pass


def test_ws_connect_with_bearer_header_mints_a_session(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    with c.websocket_connect("/ws", headers={"Authorization": "Bearer s3cret"}) as ws:
        ws.send_json({"target_node": SKIN, "requested_value": 7.0})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_MUTATION_REJECTED"  # no instance exists yet on this fresh session


def test_ws_joins_an_already_authenticated_session_via_cookie_alone(monkeypatch):
    """The real browser flow: a client authenticates via REST first (Authorization header), then
    opens the WS — which cannot set custom headers from browser JS — relying purely on the cookie
    that REST call already minted."""
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    c = TestClient(create_app())
    _bootstrap(c, Authorization="Bearer s3cret")
    assert "gtc_session" in c.cookies

    with c.websocket_connect("/ws") as ws:  # no Authorization header at all
        ws.send_json({"target_node": SKIN, "requested_value": 8.0})
        msg = ws.receive_json()
    assert msg["event_type"] == "PARAMETER_CASCADE_UPDATE"
    assert msg["mutations_applied"][0]["value"] == 8.0
    # and the mutation landed in the SAME session the earlier REST call created
    assert c.get("/ledger", ).json()["instances"]["root"]["params"]["skin_thickness_mm"]["value"] == 8.0
