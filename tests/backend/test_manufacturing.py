"""Phase 6 — manufacturability outputs: packages/manufacturing/manifest.py::build_manifest (pure),
GET /manufacturing/manifest (always-available, no export-gate check), and GET /export/step's new
`instance_id` param for per-part export (omitted must stay byte-for-byte the pre-existing behavior —
the regression risk this file specifically checks)."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

import packages.transport.app as app_module
from packages.ledger.derived_resolver import Verdict, signature_from_params
from packages.ledger.fingerprint import fingerprint
from packages.ledger.gates import ExportStatus, GateResult
from packages.ledger.schema import Connection, InterfaceRef, Instance, MasterParametricLedger
from packages.manufacturing.manifest import build_manifest
from packages.transport.app import create_app, make_core_ledger

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _fake_analyze(params, material_name, load_n, subsystem_name="bracket", cut_features=None):
    # mirrors tests/backend/test_analysis_api.py's _fake_analyze exactly
    return Verdict(geometry_signature=signature_from_params(params, geometry_params=tuple(params.keys())),
                   fingerprint=fingerprint(),
                   factor_of_safety=4.0, mesh_converged=True, watertight=True, min_wall_ok=True, solver_seconds=2.5)


# --- build_manifest() unit tests (no HTTP) --------------------------------------------------------


def _instance(iid: str, subsystem_type: str = "bracket") -> Instance:
    return Instance(id=iid, subsystem_type=subsystem_type)


def _ledger(*, material: str = "PLA", instances: dict[str, Instance] | None = None,
            connections: list[Connection] | None = None) -> MasterParametricLedger:
    led = make_core_ledger()
    structure = led.domains.structure.model_copy(update={"material_profile": material})
    domains = led.domains.model_copy(update={"structure": structure})
    led = led.model_copy(update={"domains": domains})
    if instances is not None:
        led = led.model_copy(update={"instances": instances})
    if connections is not None:
        led = led.model_copy(update={"connections": connections})
    return led


def test_build_manifest_default_pla_material_is_print_for_every_part():
    led = _ledger(instances={
        "root": _instance("root", "bracket"),
        "leg1": _instance("leg1", "standoff"),
    })
    m = build_manifest(led)
    assert m.material == "PLA"
    assert len(m.parts) == 2
    assert all(p.process == "print" for p in m.parts)


def test_build_manifest_cnc_material_is_cnc_for_every_part():
    # AL6061 is registered in packages/ledger/bom.py::MATERIAL_DB as a metal -> CNC, matching the
    # manufacturing knowledge fragment's "metal -> CNC" rule.
    led = _ledger(material="AL6061", instances={
        "root": _instance("root", "bracket"),
        "leg1": _instance("leg1", "standoff"),
    })
    m = build_manifest(led)
    assert m.material == "AL6061"
    assert len(m.parts) == 2
    assert all(p.process == "CNC" for p in m.parts)


def test_build_manifest_assembly_steps_use_kind_specific_verbs():
    conns = [
        Connection(id="c1", a=InterfaceRef(instance_id="a", interface="root"),
                   b=InterfaceRef(instance_id="b", interface="tip_right"), kind="bolted"),
        Connection(id="c2", a=InterfaceRef(instance_id="c", interface="root"),
                   b=InterfaceRef(instance_id="d", interface="tip_left"), kind="mate"),
    ]
    led = _ledger(instances={iid: _instance(iid) for iid in ("a", "b", "c", "d")}, connections=conns)
    m = build_manifest(led)
    assert len(m.assembly_steps) == 2
    assert m.assembly_steps[0] == "bolt a.root <-> b.tip_right"
    assert m.assembly_steps[1] == "mate c.root <-> d.tip_left"


def test_build_manifest_nonzero_gap_mm_appears_in_step_text():
    conns = [Connection(id="c1", a=InterfaceRef(instance_id="a", interface="root"),
                        b=InterfaceRef(instance_id="b", interface="tip_right"), gap_mm=2.5)]
    led = _ledger(instances={"a": _instance("a"), "b": _instance("b")}, connections=conns)
    m = build_manifest(led)
    assert len(m.assembly_steps) == 1
    assert "(gap 2.5mm)" in m.assembly_steps[0]


def test_build_manifest_zero_gap_mm_omits_the_gap_suffix():
    conns = [Connection(id="c1", a=InterfaceRef(instance_id="a", interface="root"),
                        b=InterfaceRef(instance_id="b", interface="tip_right"), gap_mm=0.0)]
    led = _ledger(instances={"a": _instance("a"), "b": _instance("b")}, connections=conns)
    m = build_manifest(led)
    assert "gap" not in m.assembly_steps[0]


def test_build_manifest_parts_sorted_by_instance_id_regardless_of_insertion_order():
    # inserted reverse-alphabetically (zeta before alpha) -- manifest.parts must still come out sorted
    instances = {"zeta": _instance("zeta"), "alpha": _instance("alpha")}
    led = _ledger(instances=instances)
    m = build_manifest(led)
    assert [p.instance_id for p in m.parts] == ["alpha", "zeta"]


# --- REST: GET /manufacturing/manifest ------------------------------------------------------------


def test_manufacturing_manifest_endpoint_returns_shape_without_gating():
    # a totally fresh project (no material override, no review/sign-off, no analysis run) must still
    # succeed -- this is an always-available planning artifact, not the gated export deliverable.
    c = TestClient(create_app())
    res = c.get("/manufacturing/manifest")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"material", "parts", "assembly_steps"}
    assert body["material"] == "PLA"
    assert body["parts"] == []
    assert body["assembly_steps"] == []

    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    res2 = c.get("/manufacturing/manifest")
    assert res2.status_code == 200
    body2 = res2.json()
    assert len(body2["parts"]) == 1
    part = body2["parts"][0]
    assert part["instance_id"] == "root"
    assert part["subsystem_type"] == "bracket"
    assert part["material"] == "PLA"
    assert part["process"] == "print"


# --- REST: GET /export/step?instance_id=... ---------------------------------------------------------


def test_export_step_unknown_instance_id_is_404(monkeypatch):
    # gate forced ELIGIBLE so the request actually reaches the instance_id resolution branch --
    # otherwise a fresh/unreviewed project's gate-block (409) would mask this check entirely.
    monkeypatch.setattr(app_module, "evaluate_export_gates",
                        lambda *a, **k: GateResult(status=ExportStatus.EXPORT_ELIGIBLE, reasons=[], unknowns=[]))
    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    res = c.get("/export/step", params={"instance_id": "ghost"})
    assert res.status_code == 404
    body = res.json()
    assert body["status"] == "error"
    assert "ghost" in body["message"]


def test_export_step_without_instance_id_still_gate_blocked_same_as_before():
    """Regression check: on a project with MULTIPLE instances, omitting instance_id must still hit
    the exact same gate-blocked 409 as test_export_step_enforces_gates_server_side (test_app.py) did
    before the instance_id param was added -- the new param must not have changed the default path."""
    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})
    res = c.get("/export/step")
    assert res.status_code == 409
    body = res.json()
    assert body["status"] == "error"
    assert "factor_of_safety" in body["unknowns"]
    assert any("not engineer-reviewed" in r for r in body["reasons"])


def test_export_step_with_instance_id_is_gated_on_that_instances_own_verdict_not_the_active_ones(monkeypatch):
    # 2026-07-19 review (CRITICAL): a per-part export used to gate-check whatever instance was ACTIVE,
    # not the instance_id actually being exported — a fabricated-green-light path (Inversion #1
    # violation). Sign off an analyzed 'root', add a never-analyzed 'other' (resets review), reactivate
    # + re-sign-off 'root' (flips review back without re-running any solver for 'other'), then confirm
    # exporting 'other' is STILL correctly blocked on its own unknown factor_of_safety.
    monkeypatch.setattr(app_module, "analyze_in_subprocess", _fake_analyze)

    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    c.post("/analyze")
    c.post("/signoff", params={"reviewer": "pe@example.com"})
    assert c.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"

    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "other"})  # never analyzed; resets review
    c.post("/instances/root/activate", json={})
    c.post("/signoff", params={"reviewer": "pe@example.com"})  # re-flips review using root's still-cached verdict
    assert c.post("/export/check").json()["status"] == "EXPORT_ELIGIBLE"  # (whole-project gate — root's verdict)

    res = c.get("/export/step", params={"instance_id": "other"})
    assert res.status_code == 409
    body = res.json()
    assert "factor_of_safety" in body["unknowns"]


def test_export_step_with_zero_instances_and_no_instance_id_returns_clean_error_not_a_crash(monkeypatch):
    # 2026-07-19 review (HIGH): the instance_id diff accidentally moved the `name = ...` computation
    # before the `if part is None` guard, so a zero-instance project raised an unhandled AttributeError
    # (state.active_instance() is None) instead of the pre-existing clean JSON error.
    monkeypatch.setattr(app_module, "evaluate_export_gates",
                        lambda *a, **k: GateResult(status=ExportStatus.EXPORT_ELIGIBLE, reasons=[], unknowns=[]))
    c = TestClient(create_app())
    res = c.get("/export/step")
    assert res.status_code == 200
    assert res.json() == {"status": "error", "message": "no geometry to export"}


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_export_step_with_instance_id_exports_just_that_one_part(monkeypatch):
    monkeypatch.setattr(app_module, "evaluate_export_gates",
                        lambda *a, **k: GateResult(status=ExportStatus.EXPORT_ELIGIBLE, reasons=[], unknowns=[]))
    c = TestClient(create_app())
    c.post("/instances", json={"subsystem_type": "bracket", "instance_id": "root"})
    c.post("/instances", json={"subsystem_type": "standoff", "instance_id": "leg1"})

    res = c.get("/export/step", params={"instance_id": "leg1"})
    assert res.status_code == 200
    cd = res.headers.get("content-disposition", "")
    assert "leg1.step" in cd
    assert "assembly" not in cd

    # sanity: the other part's id (or "assembly") requests a DIFFERENT export than "root"'s own
    res_root = c.get("/export/step", params={"instance_id": "root"})
    assert res_root.status_code == 200
    cd_root = res_root.headers.get("content-disposition", "")
    assert "root.step" in cd_root
