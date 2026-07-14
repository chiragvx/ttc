"""Item 3 (2026-07-03): the multi-instance outliner — add/remove/activate + activation-scoped
/params, /mesh, mutate targeting. MVP scope: editing/mesh/export/analyze always target the ONE
active instance; assembly-wide rendering across every instance is a deliberately deferred increment.
"""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from packages.transport.app import create_app

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _client():
    # a project starts as an empty workspace (2026-07-04) — bootstrap the bracket root every other
    # test here relies on, exactly as genesis used to seed it automatically.
    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    return c


def test_initial_project_starts_empty():
    """2026-07-04: a project is an empty workspace until something is added — no default seed part."""
    c = TestClient(create_app())
    r = c.get("/instances").json()
    assert r["instances"] == []


def test_first_add_instance_is_a_plain_top_level_part():
    """Parts are a flat set brought into a file (2026-07-04) — the FIRST instance ever added to an
    empty project is just a top-level part, not a "root" everything else auto-chains under (see
    packages/ledger/apply.py::resolve_instance_parent)."""
    c = TestClient(create_app())
    r = c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"}).json()
    assert r == {"ok": True, "instance_id": "leg1"}
    rows = c.get("/instances").json()
    assert len(rows["instances"]) == 1
    row = rows["instances"][0]
    assert row["id"] == "leg1" and row["subsystem_type"] == "standoff" and row["parent_id"] is None
    assert row["is_active"] is True


def test_add_instance_preserves_prior_mutation_history():
    """Regression: instance add/remove used to WIPE the whole event log and re-genesis, silently
    discarding every earlier mutation. It now appends an incremental INSTANCE_ADDED fact instead —
    a mutation made BEFORE adding a second instance must still be present after."""
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "instances.root.params.skin_thickness_mm", "requested_value": 3.5})
        ws.receive_json()
    assert c.get("/ledger").json()["instances"]["root"]["params"]["skin_thickness_mm"]["value"] == 3.5

    c.post("/instances", json={"subsystem_type": "standoff"})

    led = c.get("/ledger").json()
    assert led["instances"]["root"]["params"]["skin_thickness_mm"]["value"] == 3.5  # survived
    assert any(i["subsystem_type"] == "standoff" for i in led["instances"].values())


def test_add_instance_appears_and_becomes_active():
    c = _client()
    r = c.post("/instances", json={"subsystem_type": "standoff"}).json()
    assert r["ok"] is True
    new_id = r["instance_id"]

    rows = {i["id"]: i for i in c.get("/instances").json()["instances"]}
    assert new_id in rows
    assert rows[new_id]["subsystem_type"] == "standoff"
    assert rows[new_id]["parent_id"] is None  # omitted parent_id -> top-level, no auto-chaining
    assert rows[new_id]["is_active"] is True
    assert rows["root"]["is_active"] is False


def test_add_instance_with_explicit_id_and_parent():
    c = _client()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    r = c.post("/instances", json={"subsystem_type": "washer", "instance_id": "washer1",
                                   "parent_id": "leg1"}).json()
    assert r == {"ok": True, "instance_id": "washer1"}
    rows = {i["id"]: i for i in c.get("/instances").json()["instances"]}
    assert rows["washer1"]["parent_id"] == "leg1"


def test_add_instance_unknown_subsystem_is_rejected():
    c = _client()
    r = c.post("/instances", json={"subsystem_type": "not_a_real_part"}).json()
    assert r["ok"] is False
    assert "not_a_real_part" in r["error"]
    # rejected add must not mutate the tree
    assert len(c.get("/instances").json()["instances"]) == 1


def test_add_instance_duplicate_id_is_rejected():
    c = _client()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    r = c.post("/instances", json={"subsystem_type": "washer", "instance_id": "leg1"}).json()
    assert r["ok"] is False


def test_params_reflects_the_active_instance_not_always_root():
    c = _client()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    r = c.get("/params").json()
    assert r["subsystem"] == "standoff"
    assert r["instance_id"] == "leg1"
    names = {row["node"].rsplit(".", 1)[-1] for row in r["params"]}
    assert {"outer_dia_mm", "inner_dia_mm", "height_mm"} <= names
    # bracket's own params must NOT leak into standoff's param list
    assert "skin_thickness_mm" not in names


def test_activate_switches_params_back():
    c = _client()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    assert c.get("/params").json()["instance_id"] == "leg1"

    r = c.post("/instances/root/activate").json()
    assert r == {"ok": True, "instance_id": "root"}
    assert c.get("/params").json()["instance_id"] == "root"


def test_activate_unknown_instance_is_rejected():
    c = _client()
    r = c.post("/instances/does-not-exist/activate").json()
    assert r["ok"] is False


def test_mutate_targets_the_named_instance_regardless_of_active_pointer():
    """A mutation's dotted target already encodes which instance it addresses — apply it correctly
    even when a DIFFERENT instance is currently active in the outliner."""
    c = _client()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    c.post("/instances/root/activate")  # root is active again; leg1 still exists

    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "instances.leg1.params.height_mm", "requested_value": 30.0})
        msg = ws.receive_json()
    assert msg["mutations_applied"][0]["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert led["instances"]["leg1"]["params"]["height_mm"]["value"] == 30.0
    # root's own params are untouched
    assert led["instances"]["root"]["params"]["skin_thickness_mm"]["value"] == 2.0


def test_delete_allows_childless_root_returning_to_empty_project():
    """2026-07-04: the old "root can never be removed" rule blocked the single most natural Undo — a
    user's very first added part IS the root, so refusing to remove it made "undo my first add"
    permanently fail. Root removal is fine when it's the ONLY instance (see
    packages/ledger/apply.py::apply_instance_op's remove_instance branch)."""
    c = _client()
    r = c.delete("/instances/root").json()
    assert r["ok"] is True
    assert c.get("/instances").json()["instances"] == []


def test_delete_refuses_instance_with_children_even_if_it_was_first():
    """Real parent-child relationships (explicit parent_id) still block removal — being the first
    part added into an empty file doesn't matter under the flat model, only having dependents does
    (an omitted parent_id, the default, would make leg1 a top-level PEER instead, not a child)."""
    c = _client()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1", "parent_id": "root"})
    r = c.delete("/instances/root").json()
    assert r["ok"] is False
    assert "leg1" in r["error"]


def test_delete_refuses_instance_with_children():
    c = _client()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    c.post("/instances", json={"subsystem_type": "washer", "instance_id": "washer1", "parent_id": "leg1"})
    r = c.delete("/instances/leg1").json()
    assert r["ok"] is False
    assert "washer1" in r["error"]


def test_delete_childless_instance_succeeds_and_reactivates_root_if_it_was_active():
    c = _client()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    assert c.get("/params").json()["instance_id"] == "leg1"  # newly added -> active

    r = c.delete("/instances/leg1").json()
    assert r["ok"] is True
    assert len(c.get("/instances").json()["instances"]) == 1
    assert c.get("/params").json()["instance_id"] == "root"  # fell back after its active instance died


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_mesh_renders_the_active_instance_geometry():
    c = _client()
    root_mesh = c.get("/mesh").json()
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    standoff_mesh = c.get("/mesh").json()
    # a standoff (tube) and a bracket (plate + holes) are different geometry -> different tessellation
    assert standoff_mesh["positions"] != root_mesh["positions"]
    assert len(standoff_mesh["positions"]) > 0


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_mesh_and_export_compose_the_whole_assembly_once_multi_instance():
    """The 'next increment' from the Item 3 MVP, now built: /mesh and /export/step show EVERY
    instance (not just the active one) once a project holds more than one, positioned via
    assembly.py's auto-layout."""
    c = _client()
    single_mesh = c.get("/mesh").json()  # root (bracket) alone

    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    assembly_mesh = c.get("/mesh").json()
    # a composed 2-instance assembly has strictly more geometry than the single root part alone
    assert len(assembly_mesh["positions"]) > len(single_mesh["positions"])

    export = c.get("/export/step")
    assert export.status_code == 200
    assert "assembly.step" in export.headers.get("content-disposition", "")


def test_telemetry_sums_mass_across_all_instances_once_multi_instance():
    c = _client()
    with c.websocket_connect("/ws") as ws:
        ws.send_json({"target_node": "instances.root.params.skin_thickness_mm", "requested_value": 2.0})
        msg1 = ws.receive_json()
    mass_before = msg1["telemetry_delta"]["total_mass_g"]

    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    with c.websocket_connect("/ws") as ws:
        # mutate the NEW instance -- the cascade's telemetry must reflect the WHOLE assembly, not
        # just the newly-active standoff alone (which would be a tiny fraction of the bracket's mass)
        ws.send_json({"target_node": "instances.leg1.params.height_mm", "requested_value": 15.0})
        msg2 = ws.receive_json()
    mass_after = msg2["telemetry_delta"]["total_mass_g"]

    assert mass_after > mass_before  # the standoff's own mass got added on top of the bracket's
