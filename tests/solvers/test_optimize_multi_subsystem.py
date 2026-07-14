"""Optimize sweep generalized past bracket-only (2026-07-03): `_run_optimize` now discovers and sweeps
ANY fea_eligible subsystem's own thickness-like param (whichever `ParamSpec` ends in `thickness_mm`,
the same convention `_min_wall_ok` already relies on) instead of a hardcoded `skin_thickness_mm` +
bracket-shaped mass formula.

Same two-group split as the sibling `test_analysis_multi_subsystem.py` (this file's `analyze_geometry`
generalization, written the same week):
  * the "no param to sweep" short-circuit (a subsystem with no `*thickness_mm` param, e.g. `standoff`)
    runs EVERYWHERE, including this Windows dev box — and proves the point more strongly than a mock
    could: `_run_optimize` genuinely never imports the solver, gmsh included, when there's nothing to
    sweep.
  * the actual sweep (bracket regression + a newly-eligible subsystem) mocks `evaluate_fs` (to avoid a
    real ccx solve) but still needs `gmsh` importable for the mock to patch onto — `needs_gmsh`,
    skipped on Windows, runs in the container.
"""

from __future__ import annotations

import importlib.util

import pytest

from packages.truth_plane.analysis import _run_optimize, _thickness_param_name

HAS_B123D = importlib.util.find_spec("build123d") is not None
HAS_GMSH = importlib.util.find_spec("gmsh") is not None

needs_b123d = pytest.mark.skipif(not HAS_B123D, reason="needs build123d to build geometry")
needs_gmsh = pytest.mark.skipif(not HAS_GMSH, reason="needs gmsh (Linux container) to mock evaluate_fs")


def _fake_evaluate_fs(monkeypatch, *, factor_of_safety=4.2, status="OK"):
    """Patch the solver call `analyze_geometry` lazily imports, and record every invocation."""
    import packages.truth_plane.solvers.fs as fs_module
    from packages.truth_plane.solvers.fs import FsVerdict

    calls: list[dict] = []

    def _fake(step_path, **kwargs):
        calls.append(kwargs)
        return FsVerdict(status=status, factor_of_safety=factor_of_safety, max_von_mises_mpa=10.0,
                         tip_deflection_mm=0.1, converged=True, stress_drift_pct=1.0)

    monkeypatch.setattr(fs_module, "evaluate_fs", _fake)
    return calls


# ------------------------------------------------------------------------------------------------
# No-sweep-target short-circuit — runs everywhere, no gmsh required. This is the load-bearing safety
# test: if a no-thickness-param subsystem's optimize path ever accidentally reached the solver import,
# THIS WOULD FAIL with ModuleNotFoundError on any box without gmsh (rather than silently mocking it away).
# ------------------------------------------------------------------------------------------------

def test_thickness_param_name_none_when_no_such_param():
    from packages.subsystems import get_subsystem_model
    sub = get_subsystem_model("standoff")
    # standoff's params are outer_dia_mm/inner_dia_mm/height_mm — none end in thickness_mm
    assert _thickness_param_name(sub) is None


def test_run_optimize_short_circuits_for_no_sweep_target_subsystem():
    """`_run_optimize` on a subsystem with no thickness-like param returns the documented empty result
    WITHOUT crashing and WITHOUT ever invoking the solver (or even importing anything solver-related) —
    this runs fine even without gmsh present."""
    base_params = {
        "instances.root.params.outer_dia_mm": 10.0,
        "instances.root.params.inner_dia_mm": 4.0,
        "instances.root.params.height_mm": 15.0,
    }
    result = _run_optimize("standoff", [2.0, 3.0, 4.0], base_params, "PLA", 40.0, 2.0)
    assert result == {"variants": [], "best_value": None, "best_mass_g": None,
                      "best_verdict": None, "param_name": None}


# ------------------------------------------------------------------------------------------------
# Actual sweep — needs gmsh importable so the mock has something to patch onto.
# ------------------------------------------------------------------------------------------------

@needs_b123d
@needs_gmsh
def test_bracket_sweep_shape_when_all_candidates_pass(monkeypatch):
    """Sanity check on the return shape using the verbatim shared fake: when every candidate clears
    the FS floor, the lightest (thinnest) candidate wins."""
    calls = _fake_evaluate_fs(monkeypatch, factor_of_safety=7.0)
    base_params = {
        "instances.root.params.skin_thickness_mm": 2.0,
        "instances.root.params.internal_rib_spacing_mm": 20.0,
        "instances.root.params.plate_width_mm": 60.0,
        "instances.root.params.plate_depth_mm": 40.0,
        "instances.root.params.hole_diameter_mm": 6.0,
        "instances.root.params.hole_count": 4,
    }
    result = _run_optimize("bracket", [2.0, 3.0, 4.0], base_params, "PLA", 40.0, 2.0)

    assert len(calls) == 3
    assert result["param_name"] == "skin_thickness_mm"
    assert all(v["feasible"] for v in result["variants"])
    assert result["best_value"] == 2.0  # lightest of an all-feasible sweep = the thinnest candidate


@needs_b123d
@needs_gmsh
def test_bracket_sweep_behavior_preserved(monkeypatch):
    """Regression guard: generalizing `_run_optimize` must not change bracket's own behavior — sweep
    skin_thickness_mm candidates against a fake FS that passes only at/above a threshold, and pick the
    LIGHTEST feasible value."""
    import packages.truth_plane.solvers.fs as fs_module
    from packages.truth_plane.solvers.fs import FsVerdict

    calls: list[dict] = []
    fs_by_call_index = [1.0, 2.0, 4.0]  # thin fails, mid fails, thick passes a floor of 2.0

    def _fake_sequenced(step_path, **kwargs):
        calls.append(kwargs)
        idx = len(calls) - 1
        fs = fs_by_call_index[idx]
        return FsVerdict(status="OK", factor_of_safety=fs, max_von_mises_mpa=10.0,
                         tip_deflection_mm=0.1, converged=True, stress_drift_pct=1.0)

    monkeypatch.setattr(fs_module, "evaluate_fs", _fake_sequenced)

    base_params = {
        "instances.root.params.skin_thickness_mm": 2.0,
        "instances.root.params.internal_rib_spacing_mm": 20.0,
        "instances.root.params.plate_width_mm": 60.0,
        "instances.root.params.plate_depth_mm": 40.0,
        "instances.root.params.hole_diameter_mm": 6.0,
        "instances.root.params.hole_count": 4,
    }
    result = _run_optimize("bracket", [2.0, 3.0, 4.0], base_params, "PLA", 40.0, 2.0)

    assert len(calls) == 3
    assert result["param_name"] == "skin_thickness_mm"
    assert [v["value"] for v in result["variants"]] == [2.0, 3.0, 4.0]
    assert [v["feasible"] for v in result["variants"]] == [False, False, True]
    assert result["best_value"] == 4.0  # only feasible candidate = lightest feasible
    assert result["best_mass_g"] is not None
    assert result["best_verdict"] is not None


@needs_b123d
@needs_gmsh
def test_newly_eligible_subsystem_sweeps_its_own_thickness_param(monkeypatch):
    """`flat_bar` (thickness_mm) is newly fea_eligible — sweeping picks the lightest feasible
    thickness_mm value, using flat_bar's OWN volume function for mass (not bracket's area formula)."""
    import packages.truth_plane.solvers.fs as fs_module
    from packages.truth_plane.solvers.fs import FsVerdict

    calls: list[dict] = []
    fs_by_call_index = [1.5, 3.0, 5.0]  # only the last two clear a floor of 2.5

    def _fake_sequenced(step_path, **kwargs):
        calls.append(kwargs)
        idx = len(calls) - 1
        fs = fs_by_call_index[idx]
        return FsVerdict(status="OK", factor_of_safety=fs, max_von_mises_mpa=10.0,
                         tip_deflection_mm=0.1, converged=True, stress_drift_pct=1.0)

    monkeypatch.setattr(fs_module, "evaluate_fs", _fake_sequenced)

    base_params = {
        "instances.root.params.length_mm": 100.0,
        "instances.root.params.width_mm": 20.0,
        "instances.root.params.thickness_mm": 5.0,
    }
    result = _run_optimize("flat_bar", [3.0, 4.0, 5.0], base_params, "PLA", 40.0, 2.5)

    assert len(calls) == 3
    assert result["param_name"] == "thickness_mm"
    assert [v["value"] for v in result["variants"]] == [3.0, 4.0, 5.0]
    assert [v["feasible"] for v in result["variants"]] == [False, True, True]
    assert result["best_value"] == 4.0  # lightest of the two feasible candidates
    # flat_bar's own volume = length * width * thickness -> mass scales with the swept thickness
    assert result["best_mass_g"] is not None
    assert result["variants"][1]["mass_g"] < result["variants"][2]["mass_g"]
