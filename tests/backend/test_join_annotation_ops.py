"""JoinAnnotation (2026-07-27) — semantic HOW-joined data (bolted/press_fit/welded/adhesive/custom)
attached to an EXISTING Connection, for the BOM. Purely documentation-grade, never touches geometry
(contrast FitOp, which does). Mirrors tests/backend/test_coupling_ops.py's own conventions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.transport.app import create_app


def _client():
    return TestClient(create_app())


def _connected_pair(c):
    """Two lbracket-shaped-compatible parts mated via a real connection_ops call -- reuses the
    proven enclosure/lbracket mate from tests/subsystems/test_placement.py."""
    box = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "enclosure",
                                        "instance_id": "box"}).json()
    brk = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "lbracket",
                                        "instance_id": "brk"}).json()
    assert box["status"] == "APPLIED" and brk["status"] == "APPLIED"
    conn = c.post("/connection_ops", json={"op": "add_connection", "a_instance": "brk",
                                           "a_interface": "wall_mount", "b_instance": "box",
                                           "b_interface": "right"}).json()
    assert conn["status"] == "APPLIED"
    return conn["connection_id"]


def test_add_join_annotation_applies_and_persists_through_replay():
    c = _client()
    conn_id = _connected_pair(c)
    r = c.post("/join_annotation_ops", json={"op": "add_join_annotation", "connection_id": conn_id,
                                             "method": "bolted", "fastener": "M5x16 socket cap"}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    assert r["annotation"]["method"] == "bolted"
    assert r["annotation"]["fastener"] == "M5x16 socket cap"
    join_id = r["join_id"]
    led = c.get("/ledger").json()
    assert any(j["id"] == join_id for j in led["join_annotations"])


def test_add_join_annotation_rejects_an_unknown_connection():
    c = _client()
    r = c.post("/join_annotation_ops", json={"op": "add_join_annotation", "connection_id": "ghost",
                                             "method": "bolted"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "ghost" in r["message"]


def test_add_join_annotation_rejects_a_second_annotation_on_the_same_connection():
    c = _client()
    conn_id = _connected_pair(c)
    first = c.post("/join_annotation_ops", json={"op": "add_join_annotation", "connection_id": conn_id,
                                                  "method": "bolted"}).json()
    assert first["ok"]
    second = c.post("/join_annotation_ops", json={"op": "add_join_annotation", "connection_id": conn_id,
                                                   "method": "welded"}).json()
    assert not second["ok"] and second["status"] == "REJECTED"
    assert "already has a join annotation" in second["message"]


def test_remove_join_annotation():
    c = _client()
    conn_id = _connected_pair(c)
    added = c.post("/join_annotation_ops", json={"op": "add_join_annotation", "connection_id": conn_id,
                                                  "method": "press_fit"}).json()
    r = c.post("/join_annotation_ops", json={"op": "remove_join_annotation", "id": added["join_id"]}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert led["join_annotations"] == []


def test_remove_join_annotation_rejects_an_unknown_id():
    c = _client()
    r = c.post("/join_annotation_ops", json={"op": "remove_join_annotation", "id": "ghost"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"


def test_join_annotation_is_not_a_geometry_class_event():
    # purely semantic -- must NOT reset an engineer sign-off the way a real geometry change
    # (PARAMETER_MUTATION, FIT_BOUND, ...) would. Direct check against the actual set replay consults
    # (packages/ledger/events.py::GEOMETRY_CLASS_KINDS) -- exercising this through a real /signoff
    # would additionally require a real solver verdict to exist, unrelated to what this test covers.
    from packages.ledger.events import EventKind, GEOMETRY_CLASS_KINDS
    assert EventKind.JOIN_ANNOTATION_ADDED not in GEOMETRY_CLASS_KINDS
    assert EventKind.JOIN_ANNOTATION_REMOVED not in GEOMETRY_CLASS_KINDS
    # but IS a fact replay must reconstruct
    from packages.ledger.events import FACT_KINDS
    assert EventKind.JOIN_ANNOTATION_ADDED in FACT_KINDS
    assert EventKind.JOIN_ANNOTATION_REMOVED in FACT_KINDS


def test_fit_connector_uses_the_join_annotations_method_as_a_default_clearance():
    # a press_fit annotation between a round_post host and a spar_joiner_sleeve connector should
    # bias fit_connector's OMITTED clearance_mm negative (interference), not the neutral 0.0 default.
    c = _client()
    post = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_post",
                                         "instance_id": "post1"}).json()
    sleeve = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spar_joiner_sleeve",
                                           "instance_id": "sleeve1"}).json()
    assert post["status"] == "APPLIED" and sleeve["status"] == "APPLIED"
    conn = c.post("/connection_ops", json={"op": "add_connection", "a_instance": "sleeve1",
                                           "a_interface": "bottom", "b_instance": "post1",
                                           "b_interface": "top"}).json()
    assert conn["status"] == "APPLIED"
    c.post("/join_annotation_ops", json={"op": "add_join_annotation", "connection_id": conn["connection_id"],
                                         "method": "press_fit"})
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": "sleeve1",
                                 "host_instance": "post1"}).json()  # clearance_mm OMITTED
    assert r["ok"]
    assert r["binding"]["clearance_mm"] < 0.0  # interference, not the neutral 0.0 default


def test_fit_connector_defaults_to_neutral_clearance_with_no_join_annotation():
    c = _client()
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_post", "instance_id": "post1"})
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "spar_joiner_sleeve", "instance_id": "sleeve1"})
    r = c.post("/fit_ops", json={"op": "fit_connector", "connector_instance": "sleeve1",
                                 "host_instance": "post1"}).json()
    assert r["ok"]
    assert r["binding"]["clearance_mm"] == 0.0


def test_prompt_teaches_join_annotation_ops():
    from packages.agents.prompt_builder import build_system_prompt
    from packages.transport.app import make_demo_ledger
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "add_join_annotation" in prompt and "remove_join_annotation" in prompt
    assert "press_fit" in prompt and "bolted" in prompt and "welded" in prompt
    assert "connection_ops" in prompt  # teaches the prerequisite
