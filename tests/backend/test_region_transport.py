"""Region ledger integration (2026-08-04, Agent 8): /region_ops REST route (mirrors
/connection_ops's shape), _region_gate_findings (folded into _all_gate_findings -- an ORPHANED region
blocks export; a keep_out volume actually being physically violated stays advisory-only, already
covered by packages/truth_plane/validate.py::validate_geometry, see _region_gate_findings' own
DECISION docstring), and _coarse_drivetrain_summary (DISPLAY-ONLY, mirrors _coarse_structural_summary's
posture, never gates).

NOTE: `packages/ledger/events.py` originally shipped with NO `EventKind.REGION_ADDED`/`REGION_REMOVED`
support (that gap was outside this change's owned file list) -- the Wave 4 review caught it (a Region
could never survive `state.log.fold()`) and the repair wave landed the small, purely-additive
`append_region_added`/`append_region_removed` + `replay()` patch. The round-trip tests below
(`test_add_region_applies_and_persists_through_replay` / `test_remove_region_applies_and_persists_through_replay`)
now exercise that real path and pass.

`test_region_self_check_flags_a_live_intrusion_through_the_real_pipeline` below closes the gap R4's
review separately flagged (HIGH): every other region test here either bypasses `/region_ops` entirely
(the `_region_gate_findings` tests, hand-built `Region` objects) or bypasses persistence (the round-trip
tests never call `/validate`) -- nothing proved a region proposed through the REAL REST route, actually
persisted, with a REAL second instance placed inside it, gets flagged by the live self-check. Verified
by hand against the actual running dev server (`localhost:8001`) before being encoded here."""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.transport.app import create_app


def _client():
    return TestClient(create_app())


ADD_KW = dict(op="add_region", kind="keep_out", label="gear_train_clearance",
              x_mm=1.0, y_mm=2.0, z_mm=3.0, dx_mm=10.0, dy_mm=20.0, dz_mm=5.0)


# --- /region_ops REST route: REJECTED paths never touch the event log -- pass regardless of the
# events.py gap noted in this file's own module docstring. ------------------------------------------


def test_add_region_rejects_an_unknown_host_instance():
    c = _client()
    r = c.post("/region_ops", json={**ADD_KW, "host_instance": "ghost"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "ghost" in r["message"]


def test_add_region_rejects_a_non_positive_extent():
    c = _client()
    inst = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "enclosure"}).json()
    assert inst["status"] == "APPLIED"
    r = c.post("/region_ops", json={**ADD_KW, "host_instance": inst["instance_id"], "dx_mm": 0.0}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "> 0" in r["message"]


def test_remove_region_rejects_an_unknown_id():
    c = _client()
    r = c.post("/region_ops", json={"op": "remove_region", "id": "ghost"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"
    assert "ghost" in r["message"]


def test_remove_region_rejects_a_missing_id():
    c = _client()
    r = c.post("/region_ops", json={"op": "remove_region"}).json()
    assert not r["ok"] and r["status"] == "REJECTED"


# --- APPLIED paths: correct target behavior, currently blocked on the events.py gap (see module
# docstring). Written to the shape that should pass once events.py gains REGION_ADDED/REMOVED support. --


def test_add_region_applies_and_persists_through_replay():
    c = _client()
    inst = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "enclosure"}).json()
    assert inst["status"] == "APPLIED"
    r = c.post("/region_ops", json={**ADD_KW, "host_instance": inst["instance_id"]}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    assert r["region"]["kind"] == "keep_out"
    assert r["region"]["label"] == "gear_train_clearance"
    region_id = r["region_id"]
    led = c.get("/ledger").json()
    assert any(reg["id"] == region_id for reg in led["regions"])


def test_remove_region_applies_and_persists_through_replay():
    c = _client()
    inst = c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "enclosure"}).json()
    added = c.post("/region_ops", json={**ADD_KW, "host_instance": inst["instance_id"]}).json()
    assert added["ok"]
    r = c.post("/region_ops", json={"op": "remove_region", "id": added["region_id"]}).json()
    assert r["ok"] and r["status"] == "APPLIED"
    led = c.get("/ledger").json()
    assert led["regions"] == []


def test_region_self_check_flags_a_live_intrusion_through_the_real_pipeline():
    # The full path: /instance_ops (host) -> /region_ops (persisted via the real event log) ->
    # /instance_ops (a second, intruding instance) -> /validate (the real running self-check, not a
    # hand-built ledger). This is the exact path a live chat proposal would take end to end.
    c = _client()
    host = c.post("/instance_ops", json={
        "op": "add_instance", "subsystem_type": "round_post", "instance_id": "host1",
        "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0,
    }).json()
    assert host["status"] == "APPLIED"

    region = c.post("/region_ops", json={
        "op": "add_region", "host_instance": "host1", "kind": "keep_out", "label": "wiring_corridor",
        "x_mm": 0.0, "y_mm": 0.0, "z_mm": 30.0, "dx_mm": 20.0, "dy_mm": 20.0, "dz_mm": 20.0,
    }).json()
    assert region["ok"] and region["status"] == "APPLIED"

    intruder = c.post("/instance_ops", json={
        "op": "add_instance", "subsystem_type": "washer", "instance_id": "intruder1",
        "x_mm": 0.0, "y_mm": 0.0, "z_mm": 30.0,
    }).json()
    assert intruder["status"] == "APPLIED"

    report = c.post("/validate", json={}).json()
    region_issues = [i for i in report["geometric"]["issues"] if i["check"] == "region"]
    assert len(region_issues) == 1
    assert "wiring_corridor" in region_issues[0]["message"]
    assert set(region_issues[0]["instances"]) == {"host1", "intruder1"}


# --- _region_gate_findings: folded into _all_gate_findings -- an ORPHANED region (host removed after
# the region was added) blocks export; a region hosted by a REAL instance never does. Exercised
# directly against the pure function + a hand-built ledger, bypassing the /region_ops route entirely
# (so these are unaffected by the events.py persistence gap noted above). ----------------------------


def test_region_gate_findings_flags_an_orphaned_host(base_ledger):
    from packages.ledger.schema import Region
    from packages.transport.app import _region_gate_findings

    region = Region(id="r1", host_instance="ghost", kind="keep_out", label="orphan",
                    x_mm=0.0, y_mm=0.0, z_mm=0.0, dx_mm=1.0, dy_mm=1.0, dz_mm=1.0)
    led = base_ledger.model_copy(update={"regions": [region]})
    findings = _region_gate_findings(led)
    assert len(findings) == 1
    assert "r1" in findings[0] and "ghost" in findings[0]


def test_region_gate_findings_does_not_flag_a_region_with_a_real_host(base_ledger):
    from packages.ledger.schema import Region
    from packages.transport.app import _region_gate_findings

    region = Region(id="r1", host_instance="root", kind="keep_out", label="fine",
                    x_mm=0.0, y_mm=0.0, z_mm=0.0, dx_mm=1.0, dy_mm=1.0, dz_mm=1.0)
    led = base_ledger.model_copy(update={"regions": [region]})
    assert _region_gate_findings(led) == []


def test_region_gate_findings_empty_regions_list_is_empty(base_ledger):
    from packages.transport.app import _region_gate_findings
    assert _region_gate_findings(base_ledger) == []


def test_region_gate_findings_scoped_to_instance_id_misses_an_orphan_hosted_elsewhere(base_ledger):
    """An orphaned region (host already gone) can never be scoped under any SURVIVING instance id --
    see _region_gate_findings' own docstring on why this is correct, not a bug: the whole-ledger scan
    (instance_id=None) still reaches it."""
    from packages.ledger.schema import Region
    from packages.transport.app import _region_gate_findings

    region = Region(id="r1", host_instance="ghost", kind="keep_out", label="orphan",
                    x_mm=0.0, y_mm=0.0, z_mm=0.0, dx_mm=1.0, dy_mm=1.0, dz_mm=1.0)
    led = base_ledger.model_copy(update={"regions": [region]})
    assert _region_gate_findings(led, "root") == []
    assert len(_region_gate_findings(led, None)) == 1


def test_orphaned_region_folded_into_all_gate_findings_blocks_export(base_ledger):
    from packages.ledger.schema import Region
    from packages.transport.app import _all_gate_findings

    region = Region(id="r1", host_instance="ghost", kind="keep_out", label="orphan",
                    x_mm=0.0, y_mm=0.0, z_mm=0.0, dx_mm=1.0, dy_mm=1.0, dz_mm=1.0)
    led = base_ledger.model_copy(update={"regions": [region]})
    reasons, unknowns = _all_gate_findings(led)
    assert any("ghost" in r and "r1" in r for r in reasons)


def test_a_valid_region_never_appears_in_all_gate_findings(base_ledger):
    from packages.ledger.schema import Region
    from packages.transport.app import _all_gate_findings

    region = Region(id="r1", host_instance="root", kind="keep_out", label="fine",
                    x_mm=0.0, y_mm=0.0, z_mm=0.0, dx_mm=1.0, dy_mm=1.0, dz_mm=1.0)
    led = base_ledger.model_copy(update={"regions": [region]})
    reasons, unknowns = _all_gate_findings(led)
    assert not any("r1" in r for r in reasons)


# --- _coarse_drivetrain_summary: DISPLAY-ONLY, mirrors _coarse_structural_summary's own posture --
# never gates (ok is always True, no severity="error" is ever emitted), reads Agent 1's gear-ratio
# relations via Agent 2's derived_param_value. --------------------------------------------------------


def test_coarse_drivetrain_summary_no_couplings_is_empty_and_ok(base_ledger):
    from packages.transport.app import _coarse_drivetrain_summary
    report = _coarse_drivetrain_summary(base_ledger)
    assert report.ok
    assert report.issues == []


def test_coarse_drivetrain_summary_ignores_non_gear_couplings(base_ledger):
    from packages.ledger.schema import Coupling, CouplingInput
    from packages.transport.app import _coarse_drivetrain_summary

    led = base_ledger.model_copy(update={"couplings": [
        Coupling(id="c1", target_instance="root", relation="force_from_mass_accel",
                 inputs={"mass_g": CouplingInput(value=500.0), "accel_g": CouplingInput(value=4.0)},
                 target_param="some_param"),
    ]})
    report = _coarse_drivetrain_summary(led)
    assert report.ok
    assert report.issues == []


def test_coarse_drivetrain_summary_never_gates_even_on_an_unresolvable_gear_coupling(base_ledger):
    from packages.ledger.schema import Coupling
    from packages.transport.app import _coarse_drivetrain_summary

    led = base_ledger.model_copy(update={"couplings": [
        Coupling(id="c1", target_instance="root", relation="gear_ratio_speed_out",
                 inputs={}, target_param="output_rpm"),
    ]})
    report = _coarse_drivetrain_summary(led)
    assert report.ok  # DISPLAY-ONLY -- never flips to not-ok
    assert all(i.severity != "error" for i in report.issues)


def test_coarse_drivetrain_summary_matching_value_is_info(base_ledger):
    """Hand-computed: rpm_in=1000, teeth_in=20, teeth_out=40 -> rpm_out = 1000*20/40 = 500.0 rpm
    (packages/couplings/relations.py::gear_ratio_speed_out's own stated formula:
    rpm_out = rpm_in * teeth_in / teeth_out). Stored value matches -> severity stays "info"."""
    from packages.ledger.parameter import ParameterDef
    from packages.ledger.schema import Coupling, CouplingInput
    from packages.transport.app import _coarse_drivetrain_summary

    root = base_ledger.instances["root"]
    new_params = dict(root.params)
    new_params["output_rpm"] = ParameterDef(value=500.0, unit="rpm", bounds=(0.0, 10_000.0))
    new_instances = dict(base_ledger.instances)
    new_instances["root"] = root.model_copy(update={"params": new_params})
    led = base_ledger.model_copy(update={
        "instances": new_instances,
        "couplings": [Coupling(id="c1", target_instance="root", relation="gear_ratio_speed_out",
                               inputs={"rpm_in": CouplingInput(value=1000.0),
                                      "teeth_in": CouplingInput(value=20.0),
                                      "teeth_out": CouplingInput(value=40.0)},
                               target_param="output_rpm")],
    })
    report = _coarse_drivetrain_summary(led)
    assert report.ok
    assert len(report.issues) == 1
    assert report.issues[0].severity == "info"
    assert "500" in report.issues[0].message


def test_coarse_drivetrain_summary_mismatch_is_warning_but_still_ok(base_ledger):
    """Same hand-computed 500.0 rpm prediction as above, but the ledger stores a clearly different
    value (200.0) -- MISMATCH, severity escalates to "warning", but `ok` STAYS True (DISPLAY-ONLY,
    never gates -- this is the specific behavior the task requires be tested)."""
    from packages.ledger.parameter import ParameterDef
    from packages.ledger.schema import Coupling, CouplingInput
    from packages.transport.app import _coarse_drivetrain_summary

    root = base_ledger.instances["root"]
    new_params = dict(root.params)
    new_params["output_rpm"] = ParameterDef(value=200.0, unit="rpm", bounds=(0.0, 10_000.0))
    new_instances = dict(base_ledger.instances)
    new_instances["root"] = root.model_copy(update={"params": new_params})
    led = base_ledger.model_copy(update={
        "instances": new_instances,
        "couplings": [Coupling(id="c1", target_instance="root", relation="gear_ratio_speed_out",
                               inputs={"rpm_in": CouplingInput(value=1000.0),
                                      "teeth_in": CouplingInput(value=20.0),
                                      "teeth_out": CouplingInput(value=40.0)},
                               target_param="output_rpm")],
    })
    report = _coarse_drivetrain_summary(led)
    assert report.ok  # STILL true
    assert len(report.issues) == 1
    assert report.issues[0].severity == "warning"
    assert "MISMATCH" in report.issues[0].message


def test_coarse_drivetrain_summary_torque_relation_hand_computed(base_ledger):
    """Hand-computed: torque_in_nmm=100, teeth_in=20, teeth_out=40 ->
    torque_out_nmm = 100 * 40 / 20 = 200.0 N*mm (gear_ratio_torque_out's own stated formula:
    torque_out_nmm = torque_in_nmm * teeth_out / teeth_in)."""
    from packages.ledger.parameter import ParameterDef
    from packages.ledger.schema import Coupling, CouplingInput
    from packages.transport.app import _coarse_drivetrain_summary

    root = base_ledger.instances["root"]
    new_params = dict(root.params)
    new_params["output_torque_nmm"] = ParameterDef(value=200.0, unit="N*mm", bounds=(0.0, 10_000.0))
    new_instances = dict(base_ledger.instances)
    new_instances["root"] = root.model_copy(update={"params": new_params})
    led = base_ledger.model_copy(update={
        "instances": new_instances,
        "couplings": [Coupling(id="c1", target_instance="root", relation="gear_ratio_torque_out",
                               inputs={"torque_in_nmm": CouplingInput(value=100.0),
                                      "teeth_in": CouplingInput(value=20.0),
                                      "teeth_out": CouplingInput(value=40.0)},
                               target_param="output_torque_nmm")],
    })
    report = _coarse_drivetrain_summary(led)
    assert report.ok
    assert len(report.issues) == 1
    assert report.issues[0].severity == "info"
    assert "200" in report.issues[0].message


def test_coarse_drivetrain_summary_untargeted_gear_coupling_not_silently_dropped(base_ledger):
    from packages.ledger.schema import Coupling, CouplingInput
    from packages.transport.app import _coarse_drivetrain_summary

    led = base_ledger.model_copy(update={"couplings": [
        Coupling(id="c1", target_instance="root", relation="gear_ratio_torque_out",
                 inputs={"torque_in_nmm": CouplingInput(value=100.0),
                        "teeth_in": CouplingInput(value=20.0),
                        "teeth_out": CouplingInput(value=40.0)}),  # no target_param
    ]})
    report = _coarse_drivetrain_summary(led)
    assert report.ok
    assert len(report.issues) == 1
    assert "no target_param" in report.issues[0].message


def test_coarse_drivetrain_summary_missing_stored_param_reported(base_ledger):
    from packages.ledger.schema import Coupling, CouplingInput
    from packages.transport.app import _coarse_drivetrain_summary

    led = base_ledger.model_copy(update={"couplings": [
        Coupling(id="c1", target_instance="root", relation="gear_ratio_speed_out",
                 inputs={"rpm_in": CouplingInput(value=1000.0), "teeth_in": CouplingInput(value=20.0),
                        "teeth_out": CouplingInput(value=40.0)},
                 target_param="no_such_param"),  # root has no param by this name
    ]})
    report = _coarse_drivetrain_summary(led)
    assert report.ok
    assert len(report.issues) == 1
    assert "no_such_param" in report.issues[0].message  # message names the REAL (missing) param name


def test_coarse_drivetrain_summary_never_appears_in_export_gate_findings(base_ledger):
    """DISPLAY-ONLY structural guarantee: nothing _coarse_drivetrain_summary computes ever reaches
    _all_gate_findings/the export gate -- even a MISMATCH (the "worst" case) must not block export."""
    from packages.ledger.parameter import ParameterDef
    from packages.ledger.schema import Coupling, CouplingInput
    from packages.transport.app import _all_gate_findings, _coarse_drivetrain_summary

    root = base_ledger.instances["root"]
    new_params = dict(root.params)
    new_params["output_rpm"] = ParameterDef(value=999.0, unit="rpm", bounds=(0.0, 10_000.0))
    new_instances = dict(base_ledger.instances)
    new_instances["root"] = root.model_copy(update={"params": new_params})
    led = base_ledger.model_copy(update={
        "instances": new_instances,
        "couplings": [Coupling(id="c1", target_instance="root", relation="gear_ratio_speed_out",
                               inputs={"rpm_in": CouplingInput(value=1000.0),
                                      "teeth_in": CouplingInput(value=20.0),
                                      "teeth_out": CouplingInput(value=40.0)},
                               target_param="output_rpm")],
    })
    summary = _coarse_drivetrain_summary(led)
    assert summary.issues[0].severity == "warning"  # confirms the mismatch really was detected
    reasons, unknowns = _all_gate_findings(led)
    assert not any("gear" in r.lower() or "drivetrain" in r.lower() for r in reasons)
    assert not any("gear" in u.lower() or "drivetrain" in u.lower() for u in unknowns)


# --- prompt teaching: the adoption-critical piece -- a mechanism the model is never taught to invoke
# is dead plumbing (this session's own keepout_mm lesson). ------------------------------------------


def test_prompt_teaches_region_ops():
    from packages.agents.prompt_builder import build_system_prompt
    from packages.transport.app import make_demo_ledger

    prompt = build_system_prompt(None, make_demo_ledger())
    assert "region_ops" in prompt
    assert "add_region" in prompt and "remove_region" in prompt
    assert "keep_out" in prompt and "keep_in" in prompt
    assert "RegionOp" in prompt
    # the worked example's concrete numbers must actually be present, not just abstract guidance
    assert "25" in prompt and "30" in prompt and "15" in prompt and "battery" in prompt.lower()
