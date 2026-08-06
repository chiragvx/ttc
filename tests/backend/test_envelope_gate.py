"""envelope_missing / envelope_drift (packages/truth_plane/validate.py) + the real export-gate wiring
(packages/transport/app.py::_envelope_gate_findings, gearbox-housing-generation initiative Phase 4).

Mirrors tests/backend/test_fit_ops.py's own dangling-vs-drift test shape
(test_fit_gate_findings_blocks_export_when_the_host_is_dangling /
test_fit_drift_is_a_validate_warning_not_an_export_block) one layer out, and
tests/subsystems/test_envelope.py's own `_test_housing`/`housing_model` monkeypatch technique for
exercising a subsystem that declares `envelope_socket` (no real catalog subsystem does yet — see that
file's own module docstring)."""

from __future__ import annotations

import dataclasses
import importlib.util

import pytest

from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Transform
from packages.subsystems import SUBSYSTEM_MODELS, SUBSYSTEM_REGISTRY, ParamSpec, add_instance, get_subsystem, get_subsystem_model
from packages.subsystems.base import EnvelopeSocketSpec

HAS_B123D = importlib.util.find_spec("build123d") is not None
pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")

_HOUSING_TYPE = "_test_housing_gate"


@pytest.fixture
def housing_model(monkeypatch):
    """Registers a throwaway `_test_housing_gate` Subsystem (a `flat_bar`-shaped copy with
    `envelope_socket` set) into BOTH `SUBSYSTEM_MODELS` and `SUBSYSTEM_REGISTRY` — reverted
    automatically by monkeypatch after each test. Mirrors tests/subsystems/test_envelope.py's own
    `housing_model` fixture exactly (see that file's own docstring for why BOTH registries need it —
    `group_world_bbox`'s auto-layout resolves every ledger instance, including the housing itself)."""
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


def _set_bar_dims(led, iid: str, length: float, width: float, thickness: float):
    """Same direct-mutation convention as tests/subsystems/test_envelope.py's own `_set_bar_dims` —
    bounds are advisory-only (packages/ledger/CLAUDE.md), Instance/params are plain, non-frozen models."""
    led.instances[iid].params["length_mm"] = ParameterDef(value=length, unit="mm", bounds=(-1e6, 1e6))
    led.instances[iid].params["width_mm"] = ParameterDef(value=width, unit="mm", bounds=(-1e6, 1e6))
    led.instances[iid].params["thickness_mm"] = ParameterDef(value=thickness, unit="mm", bounds=(-1e6, 1e6))


def _set_outer_dims(led, housing_id: str, width: float, depth: float, height: float):
    led.instances[housing_id].params["outer_width_mm"] = ParameterDef(value=width, unit="mm", bounds=(0.1, 2000.0))
    led.instances[housing_id].params["outer_depth_mm"] = ParameterDef(value=depth, unit="mm", bounds=(0.1, 2000.0))
    led.instances[housing_id].params["outer_height_mm"] = ParameterDef(value=height, unit="mm", bounds=(0.1, 2000.0))


def _two_member_ledger(base_ledger):
    """member1: 40x20x10 flat_bar at the origin. member2: 30x10x8 flat_bar translated to (100,0,0) —
    same hand-computed fixture as tests/subsystems/test_envelope.py's own `_two_member_ledger` (union
    bbox / hull bbox: x=135, y=20, z=10)."""
    led = add_instance(base_ledger, "flat_bar", "member1")
    _set_bar_dims(led, "member1", 40.0, 20.0, 10.0)
    led = add_instance(led, "flat_bar", "member2")
    _set_bar_dims(led, "member2", 30.0, 10.0, 8.0)
    led.instances["member2"].transform = Transform(x_mm=100.0, y_mm=0.0, z_mm=0.0)
    return led


# ------- envelope_missing: validate.py -------


def test_envelope_missing_fires_for_an_empty_wraps_list(base_ledger, housing_model):
    from packages.truth_plane.validate import validate_geometry

    led = add_instance(base_ledger, _HOUSING_TYPE, "housing1")
    report = validate_geometry(led)
    issues = [i for i in report.issues if i.check == "envelope_missing"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "housing1" in issues[0].message and "wraps" in issues[0].message and "empty" in issues[0].message
    assert issues[0].instances == ["housing1"]
    assert report.ok is False  # error-severity flips ok, same class fit_gate_findings' dangling case holds


def test_envelope_missing_fires_for_a_dangling_wraps_member(base_ledger, housing_model):
    from packages.truth_plane.validate import validate_geometry

    led = _two_member_ledger(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["member1", "ghost_member"]
    report = validate_geometry(led)
    issues = [i for i in report.issues if i.check == "envelope_missing"]
    assert len(issues) == 1
    assert "housing1" in issues[0].message
    assert "ghost_member" in issues[0].message
    assert "unknown instance id" in issues[0].message
    assert report.ok is False


def test_envelope_missing_does_not_fire_for_a_valid_fully_resolved_wraps(base_ledger, housing_model):
    from packages.truth_plane.validate import validate_geometry

    led = _two_member_ledger(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["member1", "member2"]
    _set_outer_dims(led, "housing1", 135.0, 20.0, 10.0)  # correct, freshly-derived dims
    report = validate_geometry(led)
    assert not any(i.check == "envelope_missing" for i in report.issues)


def test_no_envelope_missing_findings_when_no_housing_family_instance_exists(base_ledger):
    from packages.truth_plane.validate import validate_geometry

    led = _two_member_ledger(base_ledger)
    report = validate_geometry(led)
    assert not any(i.check == "envelope_missing" for i in report.issues)


# ------- envelope_drift: validate.py -------


def test_envelope_drift_fires_after_a_wrapped_member_moves(base_ledger, housing_model):
    from packages.subsystems.envelope import compute_envelope
    from packages.truth_plane.validate import validate_geometry

    led = _two_member_ledger(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["member1", "member2"]
    # a REAL fresh compute at the ORIGINAL member2 position -- not a hand-computed literal, since
    # base_ledger's own "bracket" root instance participates in this file's auto-layout and shifts
    # member1/member2 off the hand-computable origin-relative positions tests/subsystems/
    # test_envelope.py's own fixture (a bare 2-flat_bar ledger, no third instance) can assume.
    fresh_before = compute_envelope(led, "housing1")
    assert fresh_before.ok is True
    _set_outer_dims(led, "housing1", fresh_before.values["hull_bbox_x_mm"],
                    fresh_before.values["hull_bbox_y_mm"], fresh_before.values["hull_bbox_z_mm"])

    # confirm it's genuinely fresh BEFORE the move -- no drift yet
    report_before = validate_geometry(led)
    assert not any(i.check == "envelope_drift" for i in report_before.issues)

    # move member2 further out along X -- widens the group's X extent, y/z unaffected.
    orig_x = led.instances["member2"].transform.x_mm
    led.instances["member2"].transform = Transform(x_mm=orig_x + 100.0, y_mm=0.0, z_mm=0.0)
    fresh_after = compute_envelope(led, "housing1")
    assert fresh_after.ok is True
    assert fresh_after.values["hull_bbox_x_mm"] != pytest.approx(fresh_before.values["hull_bbox_x_mm"])

    report_after = validate_geometry(led)
    issues = [i for i in report_after.issues if i.check == "envelope_drift"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert "housing1" in issues[0].message
    assert "outer_width_mm" in issues[0].message
    assert str(fresh_before.values["hull_bbox_x_mm"]) in issues[0].message  # the stale stored value
    assert f"{fresh_after.values['hull_bbox_x_mm']:.3f}" in issues[0].message  # what's implied NOW
    assert "resync_envelope" in issues[0].message
    # drift is advisory only -- must never flip ok (mirrors fit's own dangling-vs-drift split)
    assert report_after.ok is True


def test_envelope_drift_does_not_fire_when_dims_are_still_fresh(base_ledger, housing_model):
    from packages.subsystems.envelope import compute_envelope
    from packages.truth_plane.validate import validate_geometry

    led = _two_member_ledger(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["member1", "member2"]
    fresh = compute_envelope(led, "housing1")
    assert fresh.ok is True
    _set_outer_dims(led, "housing1", fresh.values["hull_bbox_x_mm"],
                    fresh.values["hull_bbox_y_mm"], fresh.values["hull_bbox_z_mm"])
    report = validate_geometry(led)
    assert not any(i.check == "envelope_drift" for i in report.issues)


# ------- envelope_missing wired into the REAL export gate -------


def test_envelope_missing_blocks_export_via_all_gate_findings(base_ledger, housing_model):
    from packages.transport.app import _all_gate_findings

    led = add_instance(base_ledger, _HOUSING_TYPE, "housing1")
    reasons, unknowns = _all_gate_findings(led)
    assert any("housing1" in r and "wraps" in r and "empty" in r for r in reasons)
    assert "envelope:housing1" in unknowns


def test_envelope_missing_dangling_member_blocks_export_via_all_gate_findings(base_ledger, housing_model):
    from packages.transport.app import _all_gate_findings

    led = _two_member_ledger(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["member1", "ghost_member"]
    reasons, unknowns = _all_gate_findings(led)
    assert any("housing1" in r and "ghost_member" in r for r in reasons)
    assert "envelope:housing1" in unknowns


def test_a_valid_wrapped_housing_never_appears_in_all_gate_findings(base_ledger, housing_model):
    from packages.transport.app import _all_gate_findings

    led = _two_member_ledger(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["member1", "member2"]
    _set_outer_dims(led, "housing1", 135.0, 20.0, 10.0)
    reasons, unknowns = _all_gate_findings(led)
    assert not any("housing1" in r for r in reasons)
    assert "envelope:housing1" not in unknowns


def test_envelope_drift_alone_never_appears_in_all_gate_findings(base_ledger, housing_model):
    # drift is advisory-only -- must never block export the way envelope_missing does.
    from packages.transport.app import _all_gate_findings

    led = _two_member_ledger(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["member1", "member2"]
    _set_outer_dims(led, "housing1", 135.0, 20.0, 10.0)
    led.instances["member2"].transform = Transform(x_mm=200.0, y_mm=0.0, z_mm=0.0)  # now stale
    reasons, unknowns = _all_gate_findings(led)
    assert not any("housing1" in r for r in reasons)
    assert "envelope:housing1" not in unknowns
