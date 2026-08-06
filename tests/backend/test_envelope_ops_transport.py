"""/envelope_ops + GET /envelope/status REST wiring (2026-08-06, gearbox-housing-generation initiative
Phase 3) -- mirrors tests/backend/test_region_transport.py's own shape.

PERSISTENCE (see packages/transport/app.py's own matching note directly above
`_trigger_envelope_derivation`): `packages/ledger/events.py` originally shipped with no EventKind for
an Instance.wraps change -- the SAME shape of gap `/region_ops` itself originally shipped with
(test_region_transport.py's own module docstring quotes it verbatim: "that gap was outside this
change's owned file list" -- a later, separate repair wave added EventKind.REGION_ADDED/REMOVED
afterward). A 2026-08-06 repair wave (R1 CONFIRMED, high -- a queued derivation against a real
wrap_group'd housing failed 100% of the time in the project's own docker-compose deployment, since the
worker's own ledger reload never saw a `wraps` list that was only ever mutated in-memory) closed it the
same way: `EventKind.ENVELOPE_WRAPPED`/`ENVELOPE_UNWRAPPED` + `append_envelope_wrapped`/
`append_envelope_unwrapped`. `test_wraps_list_survives_a_fresh_reload` below proves the fix: a
`wrap_group` call's `wraps` mutation is now durable across a fresh ledger reload (the very next REST
call), and a subsequent `resync_envelope` against that reloaded state now actually reaches the
derivation trigger instead of rejecting with "wraps list is empty". The DERIVED DIMENSIONS themselves
were never affected by this gap either way -- ordinary numeric instance params, written through the
already-durable PARAMETER_MUTATION path.

Needs build123d for the REAL synchronous compute_envelope path (skipped otherwise, mirroring
tests/subsystems/test_envelope.py's own skip)."""

from __future__ import annotations

import dataclasses
import importlib.util

import pytest
from fastapi.testclient import TestClient

from packages.subsystems import SUBSYSTEM_MODELS, SUBSYSTEM_REGISTRY, ParamSpec, get_subsystem, get_subsystem_model
from packages.subsystems.base import EnvelopeSocketSpec
from packages.transport.app import create_app

HAS_B123D = importlib.util.find_spec("build123d") is not None
pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")

_HOUSING_TYPE = "_test_housing_transport"


def _client(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "flat_bar", "instance_id": "root"})
    return c


def _set_bar_dims(c, iid: str, length: float, width: float, thickness: float):
    with c.websocket_connect("/ws") as ws:
        for name, value in (("length_mm", length), ("width_mm", width), ("thickness_mm", thickness)):
            ws.send_json({"target_node": f"instances.{iid}.params.{name}", "requested_value": value})
            ws.receive_json()


@pytest.fixture
def housing_model(monkeypatch):
    """Registers a throwaway `_test_housing_transport` Subsystem (a `flat_bar`-shaped copy, so its OWN
    geometry stays real/buildable for auto-layout, PLUS three outer_* params for the derived dims to
    land in) with `envelope_socket` set -- mirrors tests/subsystems/test_envelope.py's own
    `housing_model` fixture, extended with the outer_* params that fixture never needed (it never
    asserted anything about the housing's OWN written params; this file does)."""
    base_model = get_subsystem_model("flat_bar")
    housing = dataclasses.replace(
        base_model, name=_HOUSING_TYPE,
        params=[
            *base_model.params,
            ParamSpec("outer_width_mm", value=1.0, min=0.1, max=2000.0, unit="mm"),
            ParamSpec("outer_depth_mm", value=1.0, min=0.1, max=2000.0, unit="mm"),
            ParamSpec("outer_height_mm", value=1.0, min=0.1, max=2000.0, unit="mm"),
        ],
        envelope_socket=EnvelopeSocketSpec(dim_params={
            "hull_bbox_x_mm": "outer_width_mm",
            "hull_bbox_y_mm": "outer_depth_mm",
            "hull_bbox_z_mm": "outer_height_mm",
        }),
    )
    monkeypatch.setitem(SUBSYSTEM_MODELS, _HOUSING_TYPE, housing)
    housing_ctx = dataclasses.replace(get_subsystem("flat_bar"), name=_HOUSING_TYPE)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, _HOUSING_TYPE, housing_ctx)
    return housing


def _two_member_scene(c):
    """root: 40x20x10 flat_bar at the origin. member2: 30x10x8 flat_bar translated to (100,0,0) --
    same hand-computed fixture as tests/subsystems/test_envelope.py's own _two_member_ledger (union
    bbox / hull bbox: x=135, y=20, z=10), reused here via the REAL REST route instead of a hand-built
    ledger."""
    _set_bar_dims(c, "root", 40.0, 20.0, 10.0)
    member2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "flat_bar"}).json()["instance_id"]
    _set_bar_dims(c, member2, 30.0, 10.0, 8.0)
    moved = c.post("/instance_ops", json={
        "op": "move_instance", "instance_id": member2, "x_mm": 100.0, "y_mm": 0.0, "z_mm": 0.0,
    }).json()
    assert moved["ok"] is True
    return "root", member2


# --- REJECTED paths: never touch compute_envelope, pass regardless of build123d/the events.py gap ---


def test_wrap_group_rejects_unknown_housing_instance(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": "ghost", "member_instance_ids": ["root"],
    }).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "ghost" in r["message"]
    assert "derivation" not in r


def test_resync_envelope_rejects_unknown_housing_instance(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/envelope_ops", json={"op": "resync_envelope", "housing_instance": "ghost"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "ghost" in r["message"]


def test_resync_envelope_rejects_a_housing_that_was_never_wrapped(monkeypatch, housing_model):
    c = _client(monkeypatch)
    housing = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()
    assert housing["status"] == "APPLIED"
    r = c.post("/envelope_ops", json={
        "op": "resync_envelope", "housing_instance": housing["instance_id"],
    }).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "empty" in r["message"]


def test_unwrap_group_applies_no_derivation_triggered(monkeypatch):
    c = _client(monkeypatch)
    # unwrap_group on an already-empty wraps list REJECTS (packages/ledger/apply.py::apply_envelope_op)
    r = c.post("/envelope_ops", json={"op": "unwrap_group", "housing_instance": "root"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "empty" in r["message"]
    assert "derivation" not in r


# --- APPLIED path: the real synchronous (no REDIS_URL) derivation, end to end -----------------------


def test_wrap_group_then_sync_derivation_writes_housing_dims(monkeypatch, housing_model):
    c = _client(monkeypatch)
    root_id, member2 = _two_member_scene(c)
    housing = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()
    assert housing["status"] == "APPLIED"
    housing_id = housing["instance_id"]

    r = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing_id,
        "member_instance_ids": [root_id, member2],
    }).json()
    assert r["ok"] and r["status"] == "APPLIED"
    assert r["instance"]["wraps"] == [root_id, member2]  # the RESPONSE reflects the real, in-request mutation

    derivation = r["derivation"]
    assert derivation["status"] == "done"
    assert derivation["values"]["hull_bbox_x_mm"] == pytest.approx(135.0, abs=1e-3)
    assert derivation["values"]["hull_bbox_y_mm"] == pytest.approx(20.0, abs=1e-3)
    assert derivation["values"]["hull_bbox_z_mm"] == pytest.approx(10.0, abs=1e-3)
    assert set(derivation["applied_params"]) == {
        f"instances.{housing_id}.params.outer_width_mm",
        f"instances.{housing_id}.params.outer_depth_mm",
        f"instances.{housing_id}.params.outer_height_mm",
    }

    # the DERIVED DIMS durably persisted (ordinary PARAMETER_MUTATION path) —
    led = c.get("/ledger").json()
    hparams = led["instances"][housing_id]["params"]
    assert hparams["outer_width_mm"]["value"] == pytest.approx(135.0, abs=1e-3)
    assert hparams["outer_depth_mm"]["value"] == pytest.approx(20.0, abs=1e-3)
    assert hparams["outer_height_mm"]["value"] == pytest.approx(10.0, abs=1e-3)

    status = c.get("/envelope/status", params={"housing_instance_id": housing_id}).json()
    assert status["job_status"] == "done"
    assert status["current"]["hull_bbox_x_mm"] == pytest.approx(135.0, abs=1e-3)
    assert status["current"]["hull_bbox_y_mm"] == pytest.approx(20.0, abs=1e-3)
    assert status["current"]["hull_bbox_z_mm"] == pytest.approx(10.0, abs=1e-3)


# --- R5 regression (2026-08-06, CONFIRMED, high): SIZE alone was derived -- POSITION never was, so a
# correctly-sized housing could still fail to physically CONTAIN what it wraps. Both scenarios below
# mirror R5's own live repro methodology exactly: real /instance_ops + /connection_ops + /envelope_ops
# REST routes, not just static reading. ------------------------------------------------------------


def test_wrap_group_sync_derivation_also_aligns_the_housings_own_world_position(monkeypatch, housing_model):
    """The housing's own Transform must land on the wrapped group's real world center
    (`coarse_bbox_center_{x,y,z}_mm`), not just have its SIZE derived -- the direct fix for R5's
    Finding (a) (a correctly-sized housing whose own center didn't coincide with its wraps group's real
    center let a member poke outside the shell)."""
    c = _client(monkeypatch)
    root_id, member2 = _two_member_scene(c)
    housing_id = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()["instance_id"]

    r = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing_id,
        "member_instance_ids": [root_id, member2],
    }).json()
    assert r["ok"] and r["status"] == "APPLIED"
    values = r["derivation"]["values"]
    # hand-computable, same union bbox as the sibling test above: x[-20,115] y[-10,10] z[-5,5] -> center
    # (47.5, 0, 0).
    assert values["coarse_bbox_center_x_mm"] == pytest.approx(47.5, abs=1e-3)
    assert values["coarse_bbox_center_y_mm"] == pytest.approx(0.0, abs=1e-3)
    assert values["coarse_bbox_center_z_mm"] == pytest.approx(0.0, abs=1e-3)

    led = c.get("/ledger").json()
    t = led["instances"][housing_id]["transform"]
    assert t is not None, "the housing must now carry an explicit, aligned Transform, not None"
    assert (t["x_mm"], t["y_mm"], t["z_mm"]) == pytest.approx((47.5, 0.0, 0.0), abs=1e-3)


def test_wrap_group_sync_derivation_corrects_an_auto_layout_slot_an_unrelated_earlier_part_pushed_it_into(
        monkeypatch, housing_model):
    """R5's own Finding (b): an entirely ordinary multi-part project -- one unrelated top-level filler
    part (here a second `flat_bar`, NOT a member of `wraps`) seeded BEFORE the housing -- shoves the
    housing's auto-layout slot away from where the wraps group actually sits, with zero manual
    configuration by the user. Before this fix the housing stayed at that displaced auto-layout slot
    forever; after this fix, deriving the envelope also re-anchors it onto the group's real center."""
    c = _client(monkeypatch)
    root_id, member2 = _two_member_scene(c)
    filler = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "flat_bar"}).json()["instance_id"]
    assert filler not in (root_id, member2)

    housing_id = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()["instance_id"]
    # confirm the auto-layout displacement actually happened BEFORE derivation -- otherwise this test
    # would prove nothing (mirrors the fixture-sanity-check style test_envelope.py's own R2-regression
    # tests use).
    before = c.get("/ledger").json()["instances"][housing_id]["transform"]
    assert before is None or (before["x_mm"], before["y_mm"], before["z_mm"]) != pytest.approx(
        (47.5, 0.0, 0.0), abs=1e-3), "test setup did not actually displace the housing -- fix the fixture"

    r = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing_id,
        "member_instance_ids": [root_id, member2],
    }).json()
    assert r["ok"] and r["status"] == "APPLIED"

    led = c.get("/ledger").json()
    t = led["instances"][housing_id]["transform"]
    assert t is not None
    assert (t["x_mm"], t["y_mm"], t["z_mm"]) == pytest.approx((47.5, 0.0, 0.0), abs=1e-3), (
        "the housing must be re-anchored onto the wraps group's real center, not left at the "
        "auto-layout slot an unrelated filler part pushed it into")


def test_resync_envelope_also_realigns_position_after_a_member_moves(monkeypatch, housing_model):
    """resync_envelope re-runs the SAME derivation this fix lives in -- it must re-align position too,
    not just refresh the stale SIZE (mirrors envelope_drift's own "run resync_envelope to update it"
    remedy actually being complete now)."""
    c = _client(monkeypatch)
    root_id, member2 = _two_member_scene(c)
    housing_id = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()["instance_id"]
    c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing_id,
        "member_instance_ids": [root_id, member2],
    })

    moved = c.post("/instance_ops", json={
        "op": "move_instance", "instance_id": member2, "x_mm": 300.0, "y_mm": 0.0, "z_mm": 0.0,
    }).json()
    assert moved["ok"] is True

    resync = c.post("/envelope_ops", json={"op": "resync_envelope", "housing_instance": housing_id}).json()
    assert resync["ok"] and resync["derivation"]["status"] == "done"
    # new union: root x[-20,20], member2 (half-extents 15,5,4) at x=300 -> [285,315]; union x[-20,315]
    # -> center 147.5. y/z unchanged (0, 0).
    led = c.get("/ledger").json()
    t = led["instances"][housing_id]["transform"]
    assert t is not None
    assert (t["x_mm"], t["y_mm"], t["z_mm"]) == pytest.approx((147.5, 0.0, 0.0), abs=1e-3)


def test_wraps_list_survives_a_fresh_reload(monkeypatch, housing_model):
    """Proves the 2026-08-06 persistence repair (R1 CONFIRMED, high): a wrap_group call's `wraps`
    mutation is durable across a fresh ledger reload (the very next REST call), not just visible within
    its own response -- see this file's own module docstring."""
    c = _client(monkeypatch)
    root_id, member2 = _two_member_scene(c)
    housing = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()
    housing_id = housing["instance_id"]

    r = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing_id,
        "member_instance_ids": [root_id, member2],
    }).json()
    assert r["instance"]["wraps"] == [root_id, member2]  # real, in THIS response

    led = c.get("/ledger").json()  # a fresh reload — a brand-new request
    assert led["instances"][housing_id]["wraps"] == [root_id, member2]  # now durable, not gone

    # ... and a SEPARATE resync_envelope call against that reloaded state now actually reaches the
    # derivation trigger (housing.wraps is no longer empty from the server's perspective) instead of
    # rejecting with "wraps list is empty — wrap_group it first".
    resync = c.post("/envelope_ops", json={"op": "resync_envelope", "housing_instance": housing_id}).json()
    assert resync["ok"] and resync["status"] == "APPLIED"
    assert resync["derivation"]["status"] == "done"
    assert resync["derivation"]["values"]["hull_bbox_x_mm"] == pytest.approx(135.0, abs=1e-3)


def test_unwrap_group_also_survives_a_fresh_reload(monkeypatch, housing_model):
    """The clear-back-to-[] direction (EnvelopeOp.unwrap_group / EventKind.ENVELOPE_UNWRAPPED) gets the
    same durability as the set direction above -- not just wrap_group."""
    c = _client(monkeypatch)
    root_id, member2 = _two_member_scene(c)
    housing = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()
    housing_id = housing["instance_id"]

    wrapped = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing_id,
        "member_instance_ids": [root_id, member2],
    }).json()
    assert wrapped["ok"] and wrapped["status"] == "APPLIED"

    unwrapped = c.post("/envelope_ops", json={"op": "unwrap_group", "housing_instance": housing_id}).json()
    assert unwrapped["ok"] and unwrapped["status"] == "APPLIED"
    assert unwrapped["instance"]["wraps"] == []

    led = c.get("/ledger").json()  # a fresh reload — a brand-new request
    assert led["instances"][housing_id]["wraps"] == []  # durably cleared, not just in-response


def test_wrap_group_with_redis_url_set_queues_and_wraps_survive_for_the_worker(monkeypatch, housing_model):
    """Reproduces R1's exact queued-path failure mode (2026-08-06 persistence repair) directly, not
    just the synchronous fallback the tests above exercise: before `EventKind.ENVELOPE_WRAPPED`
    existed, `wrap_group`'s `wraps` mutation lived only on the in-request ledger object, so a
    REDIS_URL-set request enqueued a job whose separate worker-process reload
    (`packages/truth_plane/jobs.py::_load_project_ledger` -> `log.fold()`) would find
    `housing.wraps == []` every time and fail 100% of the time -- see events.py's own
    ENVELOPE_WRAPPED docstring and this file's own module docstring. Mirrors
    tests/backend/test_analysis_api.py::
    test_queued_analyze_records_status_durably_across_the_process_boundary's own "import jobs BEFORE
    setting REDIS_URL, monkeypatch .send to a no-op" shape -- the worker side (given a real durable
    reload) is separately proven by tests/backend/test_envelope_derivation_job.py."""
    # import BEFORE REDIS_URL is set: jobs.py picks RedisBroker vs StubBroker ONCE at import time
    # (same rationale test_queued_analyze_... gives for its own identical import-order comment).
    import packages.truth_plane.jobs as jobs_module
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://fake/0")  # makes the ROUTE take the queued branch
    sent: dict = {}
    monkeypatch.setattr(jobs_module.run_envelope_derivation, "send",
                        lambda *a, **k: sent.setdefault("args", a))  # don't actually enqueue

    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "flat_bar", "instance_id": "root"})
    root_id, member2 = _two_member_scene(c)
    housing = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()
    housing_id = housing["instance_id"]

    r = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing_id,
        "member_instance_ids": [root_id, member2],
    }).json()
    assert r["ok"] and r["status"] == "APPLIED"
    assert r["derivation"]["status"] == "queued"
    assert len(sent["args"]) == 3 and sent["args"][2] == housing_id  # (job_id, project_id, housing_instance_id)

    status = c.get("/envelope/status", params={"housing_instance_id": housing_id}).json()
    assert status["job_status"] == "queued"

    # the crux of R1's fix: `wraps` was durably persisted (ENVELOPE_WRAPPED, appended BEFORE the job
    # was even enqueued) -- so a worker-process reload of the SAME durable log would see it, unlike
    # before this repair where it existed only on the in-request ledger object. A fresh /ledger read
    # here folds that same durable log, proving the fact a worker's own reload would also observe.
    led = c.get("/ledger").json()
    assert led["instances"][housing_id]["wraps"] == [root_id, member2]

    # ... and resync_envelope against that same durably-wrapped state also reaches the (still queued,
    # no REDIS reply to consume in this test) derivation trigger instead of rejecting on an empty
    # wraps list -- proving the durability holds for resync's OWN state.ledger() re-fold too.
    resync = c.post("/envelope_ops", json={"op": "resync_envelope", "housing_instance": housing_id}).json()
    assert resync["ok"] and resync["status"] == "APPLIED"
    assert resync["derivation"]["status"] == "queued"


def test_envelope_status_with_no_prior_job_is_all_none(monkeypatch):
    c = _client(monkeypatch)
    status = c.get("/envelope/status").json()
    assert status == {"current": None, "job_status": None, "job_message": None}


def test_envelope_status_current_none_for_a_housing_with_no_envelope_socket(monkeypatch):
    c = _client(monkeypatch)  # "root" is a plain flat_bar — no envelope_socket
    status = c.get("/envelope/status", params={"housing_instance_id": "root"}).json()
    assert status["current"] is None


def test_envelope_status_job_status_is_scoped_per_housing_not_shared_across_housings(monkeypatch, housing_model):
    """R3 CONFIRMED (medium, 2026-08-06 repair): `job_id` used to be `f"{project_id}:envelope"` --
    scoped only by project, not by housing instance -- so two envelope derivations in the same project
    raced on one shared status slot, last-write-wins. Two housings here wrap the SAME two-member scene;
    housing1's derivation succeeds, housing2's is forced to FAIL (its own outer_width_mm HARD_LOCKed
    beforehand, so the write-back REJECTs, all-or-nothing). Pre-fix, housing2's later "failed" write
    would stomp housing1's already-"done" status (both sharing the bare project-scoped key) -- this
    proves the fix by construction, not just documents it."""
    c = _client(monkeypatch)
    root_id, member2 = _two_member_scene(c)

    housing1 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()
    housing1_id = housing1["instance_id"]
    housing2 = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": _HOUSING_TYPE}).json()
    housing2_id = housing2["instance_id"]

    # HARD_LOCK housing2's own outer_width_mm BEFORE wrapping it -- apply_delta REJECTs any write
    # targeting a HARD_LOCK param, so housing2's derivation write-back (all-or-nothing) will fail.
    with c.websocket_connect("/ws") as ws:
        ws.send_json({
            "target_node": f"instances.{housing2_id}.params.outer_width_mm",
            "requested_value": 1.0, "set_lock": "HARD_LOCK",
        })
        ws.receive_json()

    r1 = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing1_id,
        "member_instance_ids": [root_id, member2],
    }).json()
    assert r1["ok"] and r1["derivation"]["status"] == "done"

    r2 = c.post("/envelope_ops", json={
        "op": "wrap_group", "housing_instance": housing2_id,
        "member_instance_ids": [root_id, member2],
    }).json()
    # 2026-08-06 Phase 3 repair (R3 CONFIRMED, medium): the wraps-list mutation itself still applied
    # in-ledger, but the top-level ok/status now fold in the embedded derivation's own outcome (mirrors
    # the resync_envelope branch's `ok = derivation.get("status") in ("queued", "done")`) — a caller
    # checking only `ok` must not be told the envelope was derived when the write-back REJECTed.
    assert not r2["ok"] and r2["status"] == "REJECTED"
    assert r2["derivation"]["status"] == "error"
    assert "HARD_LOCK" in r2["derivation"]["message"]

    # housing1's own status must still read "done" — NOT stomped by housing2's later "failed" write.
    status1 = c.get("/envelope/status", params={"housing_instance_id": housing1_id}).json()
    assert status1["job_status"] == "done"
    status2 = c.get("/envelope/status", params={"housing_instance_id": housing2_id}).json()
    assert status2["job_status"] == "failed"
    assert "HARD_LOCK" in status2["job_message"]
