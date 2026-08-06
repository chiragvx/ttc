"""Phase 1b (2026-07-19) — ConnectionOp: the copilot MATES parts via typed interfaces instead of
hand-computing positions. apply_connection_op + /connection_ops + event-sourced persistence + the
prompt teaching interfaces/connection_ops."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from packages.transport.app import create_app

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _client():
    return TestClient(create_app())


def _bwb_and_wing(c):
    body = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bwb_fuselage"}).json()["instance_id"]
    wr = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel"}).json()["instance_id"]
    return body, wr


def test_add_connection_works_for_the_generic_bar_end_interfaces_too():
    # 2026-07-20 — proves the whole REST stack (not just the pure solver) accepts the new
    # bar_end_interfaces()-declared interfaces, not just the original hand-authored bwb_fuselage/
    # wing_panel pair.
    c = _client()
    la = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "longeron"}).json()["instance_id"]
    lb = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "longeron"}).json()["instance_id"]
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": la, "a_interface": "end_b",
                                        "b_instance": lb, "b_interface": "end_a"}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert any(conn["id"] == r["connection_id"] for conn in led["connections"])


def test_add_connection_works_for_the_generic_plate_face_interfaces_too():
    # 2026-07-20 — the second generic helper (plate_face_interfaces), REST round-trip.
    c = _client()
    tray = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "avionics_tray"}).json()["instance_id"]
    div = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "battery_bay_divider"}).json()["instance_id"]
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": tray, "a_interface": "top",
                                        "b_instance": div, "b_interface": "bottom"}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert any(conn["id"] == r["connection_id"] for conn in led["connections"])


def test_add_connection_applies_and_persists_through_replay():
    c = _client()
    body, wr = _bwb_and_wing(c)
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                        "b_instance": body, "b_interface": "tip_right"}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    cid = r["connection_id"]
    # persisted through the event log -> a fresh ledger read still has it
    led = c.get("/ledger").json()
    assert any(conn["id"] == cid for conn in led["connections"])


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_connection_places_the_wing_at_the_body_tip():
    c = _client()
    body, wr = _bwb_and_wing(c)
    # before connecting, the wing is auto-laid-out (off to +Y), not on the tip
    c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                    "b_instance": body, "b_interface": "tip_right"})
    rows = {i["id"]: i for i in c.get("/instances").json()["instances"]}
    wx, wy, wz = rows[wr]["world_offset"]
    # body default span 800 -> tip at x=400; the mate must place the wing root there (not near 0/auto)
    assert wx == pytest.approx(400.0, abs=1.0)


def test_hallucinated_interface_is_rejected():
    c = _client()
    body, wr = _bwb_and_wing(c)
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "ghost",
                                        "b_instance": body, "b_interface": "tip_right"}).json()
    assert r["status"] == "REJECTED"
    assert "no interface 'ghost'" in r["message"]


def test_self_connection_is_rejected():
    c = _client()
    body, _ = _bwb_and_wing(c)
    r = c.post("/connection_ops", json={"op": "add_connection", "a_instance": body, "a_interface": "tip_right",
                                        "b_instance": body, "b_interface": "tip_left"}).json()
    assert r["status"] == "REJECTED"
    assert "itself" in r["message"]


def test_second_connection_to_an_already_claimed_interface_is_rejected():
    # 2026-07-21 audit (HIGH, live-reproduced): apply_connection_op validated everything about a
    # NEW connection except whether one of its endpoints' (instance, interface) was already claimed
    # by a DIFFERENT existing connection. resolve_placements positions each mated neighbor from its
    # host's interface frame, so two connections sharing bwb_fuselage's 'tip_right' silently placed
    # BOTH wing_panel instances at the identical world Transform — overlapping geometry that
    # connection_issues() never reported, because each connection's own two endpoints DID coincide.
    c = _client()
    body, wr1 = _bwb_and_wing(c)
    wr2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel"}).json()["instance_id"]
    first = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr1, "a_interface": "root",
                                             "b_instance": body, "b_interface": "tip_right"}).json()
    assert first["ok"] and first["status"] == "APPLIED"
    second = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr2, "a_interface": "root",
                                              "b_instance": body, "b_interface": "tip_right"}).json()
    assert second["status"] == "REJECTED"
    assert "already connected" in second["message"]
    # the first connection is untouched and no phantom second connection was recorded
    led = c.get("/ledger").json()
    assert [conn["id"] for conn in led["connections"]] == [first["connection_id"]]

    # freeing the interface (remove the first connection) must let a new one claim it — the check
    # is against the CURRENT live connection set, not history.
    c.post("/connection_ops", json={"op": "remove_connection", "id": first["connection_id"]})
    third = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr2, "a_interface": "root",
                                             "b_instance": body, "b_interface": "tip_right"}).json()
    assert third["ok"] and third["status"] == "APPLIED"


def test_remove_connection():
    c = _client()
    body, wr = _bwb_and_wing(c)
    cid = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                          "b_instance": body, "b_interface": "tip_right"}).json()["connection_id"]
    r = c.post("/connection_ops", json={"op": "remove_connection", "id": cid}).json()
    assert r["ok"]
    assert c.get("/ledger").json()["connections"] == []


def test_add_and_remove_connection_responses_carry_the_join_annotation_cascade_id_list():
    # 2026-08-05 cascade-visibility fix: ConnectionOpOutcome gains removed_join_annotation_ids
    # (remove_connection ONLY) — surfaced here so the model can notice a remove_connection call
    # cascade-dropped a JoinAnnotation. `[]`, not omitted, when nothing was cascade-removed.
    c = _client()
    body, wr = _bwb_and_wing(c)
    added = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                             "b_instance": body, "b_interface": "tip_right"}).json()
    assert added["removed_join_annotation_ids"] == []
    removed = c.post("/connection_ops", json={"op": "remove_connection", "id": added["connection_id"]}).json()
    assert removed["ok"]
    assert removed["removed_join_annotation_ids"] == []


def test_remove_connection_cascade_removed_join_annotation_is_durably_persisted():
    # R1 (2026-08-05, HIGH, live-reproduced): create_connection_op's remove_connection branch called
    # apply_connection_op (which correctly computes removed_join_annotation_ids and the REST response
    # above already reported them) but only ever appended CONNECTION_REMOVED to the event log — never
    # JOIN_ANNOTATION_REMOVED for the cascaded ids. Since state.ledger() is always the replayed log,
    # the JoinAnnotation silently survived a GET /ledger even though the response claimed it was gone.
    # Because `_next_connection_id` reuses the lowest-free id, a later connection re-landing on the
    # freed id would silently inherit a 'bolted' annotation never re-authored for it.
    c = _client()
    body, wr = _bwb_and_wing(c)
    cid = c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                          "b_instance": body, "b_interface": "tip_right"}).json()["connection_id"]
    jid = c.post("/join_annotation_ops", json={"op": "add_join_annotation", "connection_id": cid,
                                               "method": "bolted"}).json()["join_id"]
    assert any(j["id"] == jid for j in c.get("/ledger").json()["join_annotations"])

    removed = c.post("/connection_ops", json={"op": "remove_connection", "id": cid}).json()
    assert removed["ok"]
    assert removed["removed_join_annotation_ids"] == [jid]

    led = c.get("/ledger").json()
    assert led["connections"] == []
    assert led["join_annotations"] == [], (
        "cascaded JoinAnnotation must be durably removed from the replayed ledger, "
        "not just reported in the response"
    )


def test_removing_an_instance_cascade_removes_its_connections_and_survives_replay():
    # 2026-07-19 review (MEDIUM): a dangling connection whose part was removed would silently
    # resurrect onto an id-reused new part (wrong geometry + false 'joined'). Removing an instance
    # must cascade-remove its connections, persisted so replay reproduces the cascade — no resurrection.
    c = _client()
    body, wr = _bwb_and_wing(c)
    c.post("/connection_ops", json={"op": "add_connection", "a_instance": wr, "a_interface": "root",
                                    "b_instance": body, "b_interface": "tip_right"})
    assert len(c.get("/ledger").json()["connections"]) == 1
    c.post("/instance_ops", json={"op": "remove_instance", "instance_id": wr})
    assert c.get("/ledger").json()["connections"] == []          # cascade-removed (and via replay)
    # re-adding the same type reuses the id — the stale connection must NOT come back
    wr2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel"}).json()["instance_id"]
    assert wr2 == wr  # id reuse (lowest-free)
    assert c.get("/ledger").json()["connections"] == []


def test_prompt_teaches_interfaces_and_connection_ops():
    from packages.agents.prompt_builder import build_system_prompt
    from packages.transport.app import make_demo_ledger
    prompt = build_system_prompt(None, make_demo_ledger())
    # the interfaces are listed in the part-types menu
    assert "tip_left" in prompt and "tip_right" in prompt and "mate points" in prompt
    # and the connection_ops capability is taught
    assert "connection_ops" in prompt and "add_connection" in prompt
