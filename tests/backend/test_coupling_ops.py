"""Phase 2b (2026-07-19) — CouplingOp: the copilot WIRES a load onto a part from another part's
condition via a registered relation (packages/couplings/relations.py) instead of stating a load
scalar. Mirrors tests/backend/test_connection_ops.py: same TestClient pattern, same categories of
test (apply-and-persist-through-replay, a rejection case, a self-reference-style rejection case,
remove, a cascade-on-instance-removal case, and a prompt-teaches-it case)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.transport.app import create_app


def _client():
    return TestClient(create_app())


def _two_bars(c):
    """Two simple instances: 'src' provides a duty condition, 'crank' is the coupling's target —
    mirrors tests/couplings/test_couplings.py's round_bar/bracket usage. Couplings don't need real
    interfaces/connections to exist, so plain part types are fine (and preferable — simpler)."""
    src = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bracket"}).json()["instance_id"]
    crank = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    return src, crank


def _add_pressure_coupling(c, target):
    """A complete, valid add_coupling for the real relation force_from_pressure_area, both inputs as
    literal `value`s for simplicity (per task spec)."""
    return c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": target,
        "relation": "force_from_pressure_area",
        "inputs": [
            {"name": "pressure_pa", "value": 2000000.0},
            {"name": "area_mm2", "value": 500.0},
        ],
    }).json()


def test_add_coupling_applies_and_persists_through_replay():
    c = _client()
    _, crank = _two_bars(c)
    r = _add_pressure_coupling(c, crank)
    assert r["ok"] and r["status"] == "APPLIED"
    cid = r["coupling_id"]
    # persisted through the event log -> a fresh ledger read still has it
    led = c.get("/ledger").json()
    assert any(cpl["id"] == cid for cpl in led["couplings"])


def test_add_coupling_accepts_a_per_input_rationale():
    """2026-07-19 live fix: the copilot naturally wants to explain EACH input separately (why this
    mass, why this acceleration) — CouplingInputItem used to have no `rationale` slot at all, so
    extra="forbid" rejected the WHOLE tool call the moment it tried. Never persisted/read anywhere
    (same as ParameterDelta.rationale) — this only confirms it's accepted, not silently dropped as an
    unknown-field crash."""
    c = _client()
    _, crank = _two_bars(c)
    r = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": crank,
        "relation": "force_from_pressure_area",
        "inputs": [
            {"name": "pressure_pa", "value": 2000000.0, "rationale": "rated burst pressure"},
            {"name": "area_mm2", "value": 500.0, "rationale": "bore cross-section"},
        ],
    }).json()
    assert r["ok"] and r["status"] == "APPLIED"


def test_add_coupling_with_unregistered_relation_is_rejected():
    c = _client()
    _, crank = _two_bars(c)
    r = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": crank,
        "relation": "fatigue_life",
        "inputs": [],
    }).json()
    assert r["status"] == "REJECTED"
    assert "fatigue_life" in r["message"]


def test_add_coupling_with_missing_input_is_rejected():
    c = _client()
    _, crank = _two_bars(c)
    r = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": crank,
        "relation": "force_from_pressure_area",
        "inputs": [{"name": "pressure_pa", "value": 2000000.0}],  # missing area_mm2
    }).json()
    assert r["status"] == "REJECTED"
    assert "area_mm2" in r["message"]


def test_add_coupling_with_extra_input_is_rejected():
    c = _client()
    _, crank = _two_bars(c)
    r = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": crank,
        "relation": "force_from_pressure_area",
        "inputs": [
            {"name": "pressure_pa", "value": 2000000.0},
            {"name": "area_mm2", "value": 500.0},
            {"name": "extra_bogus_input", "value": 1.0},  # not a declared input
        ],
    }).json()
    assert r["status"] == "REJECTED"
    assert "extra_bogus_input" in r["message"]


def test_add_coupling_targeting_nonexistent_instance_is_rejected():
    c = _client()
    _two_bars(c)  # instances exist but we target a bogus id anyway
    r = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": "ghost",
        "relation": "force_from_pressure_area",
        "inputs": [
            {"name": "pressure_pa", "value": 2000000.0},
            {"name": "area_mm2", "value": 500.0},
        ],
    }).json()
    assert r["status"] == "REJECTED"
    assert "ghost" in r["message"]


def test_remove_coupling():
    c = _client()
    _, crank = _two_bars(c)
    cid = _add_pressure_coupling(c, crank)["coupling_id"]
    r = c.post("/coupling_ops", json={"op": "remove_coupling", "id": cid}).json()
    assert r["ok"]
    assert c.get("/ledger").json()["couplings"] == []


def test_removing_the_target_instance_cascade_removes_its_coupling_and_survives_replay():
    # Mirrors test_removing_an_instance_cascade_removes_its_connections_and_survives_replay: a dangling
    # coupling whose TARGET was removed must not resurrect onto an id-reused new part.
    c = _client()
    _, crank = _two_bars(c)
    _add_pressure_coupling(c, crank)
    assert len(c.get("/ledger").json()["couplings"]) == 1
    c.post("/instance_ops", json={"op": "remove_instance", "instance_id": crank})
    assert c.get("/ledger").json()["couplings"] == []          # cascade-removed (and via replay)
    # re-adding the same type reuses the id — the stale coupling must NOT come back
    crank2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "round_bar"}).json()["instance_id"]
    assert crank2 == crank  # id reuse (lowest-free)
    assert c.get("/ledger").json()["couplings"] == []


def test_removing_a_from_instance_source_cascade_removes_the_coupling_and_survives_replay():
    # NEW beyond ConnectionOp: a coupling can reference an instance via `from_instance` on ANY input,
    # not just as target_instance. If apply_instance_op's cascade only checked target_instance (not
    # scanning coupling.inputs for from_instance matches), removing the SOURCE instance would leave a
    # dangling coupling that, on id reuse, silently re-sources its load from an unrelated new part.
    # Unlike the other tests, `pressure_pa` here is SOURCED (from_instance/from_param), not a literal
    # value, so it actually references `src` the way the cascade check scans for.
    c = _client()
    src, crank = _two_bars(c)
    cid = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": crank,
        "relation": "force_from_pressure_area",
        # "bracket" has no chamber_pressure_pa param — plate_width_mm is a REAL param on it (the
        # unit mismatch vs. the relation's declared "Pa" is irrelevant here; apply-time only checks
        # the source instance/param EXIST, not units — see resolve.py for the unit check).
        "inputs": [
            {"name": "pressure_pa", "from_instance": src, "from_param": "plate_width_mm"},
            {"name": "area_mm2", "value": 500.0},
        ],
    }).json()["coupling_id"]
    assert len(c.get("/ledger").json()["couplings"]) == 1
    c.post("/instance_ops", json={"op": "remove_instance", "instance_id": src})
    assert c.get("/ledger").json()["couplings"] == []          # cascade-removed (and via replay)
    # re-adding the same type reuses the id — the stale coupling must NOT come back
    src2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bracket"}).json()["instance_id"]
    assert src2 == src  # id reuse (lowest-free)
    assert c.get("/ledger").json()["couplings"] == []


def test_add_coupling_with_dangling_from_instance_is_rejected():
    # 2026-07-19 review: from_instance/from_param used to get NO existence check at apply time (unlike
    # target_instance a few lines above in the same function) — a hallucinated source silently
    # persisted as APPLIED and only degraded to "unknown" much later, at resolve time.
    c = _client()
    _, crank = _two_bars(c)
    r = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": crank,
        "relation": "force_from_pressure_area",
        "inputs": [
            {"name": "pressure_pa", "from_instance": "ghost_part", "from_param": "chamber_pressure_pa"},
            {"name": "area_mm2", "value": 500.0},
        ],
    }).json()
    assert r["status"] == "REJECTED"
    assert "ghost_part" in r["message"]
    assert c.get("/ledger").json()["couplings"] == []


def test_add_coupling_with_dangling_from_param_is_rejected():
    c = _client()
    src, crank = _two_bars(c)
    r = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": crank,
        "relation": "force_from_pressure_area",
        "inputs": [
            {"name": "pressure_pa", "from_instance": src, "from_param": "not_a_real_param"},
            {"name": "area_mm2", "value": 500.0},
        ],
    }).json()
    assert r["status"] == "REJECTED"
    assert "not_a_real_param" in r["message"]
    assert c.get("/ledger").json()["couplings"] == []


def test_add_coupling_with_duplicate_input_name_is_rejected():
    # 2026-07-19 review: a repeated input name used to pass the missing/extra check (deduped via a
    # set) and then silently keep only the LAST entry in the dict comprehension, discarding an earlier,
    # validly-wired input with zero warning — this rejects it instead.
    c = _client()
    src, crank = _two_bars(c)
    r = c.post("/coupling_ops", json={
        "op": "add_coupling",
        "target_instance": crank,
        "relation": "force_from_pressure_area",
        "inputs": [
            {"name": "pressure_pa", "from_instance": src, "from_param": "plate_width_mm"},
            {"name": "pressure_pa", "value": 2000000.0},
            {"name": "area_mm2", "value": 500.0},
        ],
    }).json()
    assert r["status"] == "REJECTED"
    assert "pressure_pa" in r["message"]
    assert c.get("/ledger").json()["couplings"] == []


def test_prompt_teaches_coupling_ops_and_a_real_relation():
    from packages.agents.prompt_builder import build_system_prompt
    from packages.transport.app import make_demo_ledger
    prompt = build_system_prompt(None, make_demo_ledger())
    assert "coupling_ops" in prompt and "add_coupling" in prompt
    assert "force_from_pressure_area" in prompt
