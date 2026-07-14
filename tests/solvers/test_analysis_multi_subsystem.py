"""FEA coverage expansion (2026-07-03): `analyze_geometry` generalized past bracket-only.

The safety-critical split under test: `fea_eligible` subsystems (single-solid, plate/bar-shaped,
sharing the SAME validated cantilever methodology as the original bracket) reach the solver and get a
real Verdict; every OTHER subsystem gets an honest `factor_of_safety=None` WITHOUT the solver ever
being invoked — the "never fabricate a green light" invariant this whole design is built around,
applied to the now-24-part catalog instead of just the original hero part.

Two groups, because `evaluate_fs`'s import chain pulls in `gmsh` (Linux container only):
  * non-eligible-path tests run EVERYWHERE, including this Windows dev box — and prove the point more
    strongly than a mock could: the "unknown" path genuinely never imports the solver, gmsh included.
  * eligible-path tests mock `evaluate_fs` (to avoid needing a real ccx solve) but still need `gmsh`
    importable for the mock to patch onto — `needs_solver`, skipped on Windows, run in the container.
The real grounded FS pipeline stays validated by test_fs_cantilever.py; this file verifies ROUTING.
"""

from __future__ import annotations

import importlib.util

import pytest

from packages.ledger.nodes import DEPTH, HOLE_DIA, SKIN, WIDTH
from packages.truth_plane.analysis import analyze_geometry

HAS_B123D = importlib.util.find_spec("build123d") is not None
HAS_GMSH = importlib.util.find_spec("gmsh") is not None

needs_b123d = pytest.mark.skipif(not HAS_B123D, reason="needs build123d to build geometry")
needs_gmsh = pytest.mark.skipif(not HAS_GMSH, reason="needs gmsh (Linux container) to mock evaluate_fs")


# ------------------------------------------------------------------------------------------------
# Non-eligible path — runs everywhere, no gmsh required. This is the load-bearing safety test: if a
# non-eligible subsystem's code path ever accidentally reached the solver import, THIS WOULD FAIL
# with ModuleNotFoundError on any box without gmsh (rather than silently mocking it away).
# ------------------------------------------------------------------------------------------------

@needs_b123d
@pytest.mark.parametrize("name,params", [
    ("standoff", {"instances.root.params.outer_dia_mm": 10.0, "instances.root.params.inner_dia_mm": 4.0,
                 "instances.root.params.height_mm": 15.0}),
    ("hub", {}),
    ("shaft_collar", {}),
    ("threaded_boss", {}),
    ("hex_nut", {}),
    ("hex_bar", {}),
    ("hex_standoff", {}),
    ("dowel_pin", {}),
    ("square_tube", {}),
    ("washer", {}),
    # multi-box unions — excluded despite being "plate/bar-shaped": unverified multi-face-cap risk
    ("t_bar", {}),
    ("z_bracket", {}),
    # compound assemblies — never eligible regardless of any per-body shape
    ("enclosure", {}),
    ("table", {}),
    ("standoff_frame", {}),
])
def test_non_eligible_subsystem_never_touches_the_solver(name, params):
    """The safety invariant: an unvetted part type gets an honest 'unknown', and the solver — the
    expensive, authoritative source of a safety number — is never even invoked (never even IMPORTED,
    since this runs happily without gmsh on this Windows box)."""
    v = analyze_geometry(params, "PLA", 40.0, name)
    assert v.factor_of_safety is None
    assert v.mesh_converged is False
    assert v.solver_seconds == 0.0
    assert v.watertight is True  # geometry itself still built fine — just no FS claim
    assert len(v.geometry_signature) == 64  # still a valid, deterministic signature


# ------------------------------------------------------------------------------------------------
# Eligible path — needs gmsh importable so the mock has something to patch onto.
# ------------------------------------------------------------------------------------------------

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


@needs_b123d
@needs_gmsh
def test_bracket_still_gets_a_real_fs_path(monkeypatch):
    """Regression guard: generalizing analyze_geometry must not change bracket's own behavior — the
    ORIGINAL validated hero part, unaffected by the catalog-wide generalization."""
    calls = _fake_evaluate_fs(monkeypatch)
    v = analyze_geometry({SKIN: 3.0, WIDTH: 60.0, DEPTH: 40.0, HOLE_DIA: 6.0}, "PLA", 40.0)
    assert len(calls) == 1
    assert v.factor_of_safety == 4.2
    assert v.mesh_converged is True
    assert v.watertight is True


@needs_b123d
@needs_gmsh
@pytest.mark.parametrize("name,params", [
    ("flat_bar", {"instances.root.params.length_mm": 100.0, "instances.root.params.width_mm": 20.0,
                 "instances.root.params.thickness_mm": 5.0}),
    ("panel", {"instances.root.params.width_mm": 100.0, "instances.root.params.height_mm": 80.0,
              "instances.root.params.thickness_mm": 3.0}),
    ("cover_plate", {"instances.root.params.width_mm": 60.0, "instances.root.params.height_mm": 40.0,
                     "instances.root.params.thickness_mm": 3.0}),
    ("motor_mount", {"instances.root.params.plate_size_mm": 42.0, "instances.root.params.thickness_mm": 5.0}),
    ("mounting_plate_grid", {"instances.root.params.width_mm": 120.0, "instances.root.params.thickness_mm": 4.0}),
])
def test_newly_eligible_subsystem_reaches_the_solver(monkeypatch, name, params):
    calls = _fake_evaluate_fs(monkeypatch, factor_of_safety=7.0)
    v = analyze_geometry(params, "PLA", 40.0, name)
    assert len(calls) == 1, f"{name} should be fea_eligible and reach the (mocked) solver"
    assert v.factor_of_safety == 7.0
    assert v.mesh_converged is True


@needs_b123d
@needs_gmsh
def test_min_wall_ok_generalizes_past_the_skin_thickness_name(monkeypatch):
    """The generic min-wall check must catch ANY *_thickness_mm param below the FDM floor, not just
    bracket's specifically-named skin_thickness_mm."""
    _fake_evaluate_fs(monkeypatch)
    thin = analyze_geometry({"instances.root.params.length_mm": 100.0, "instances.root.params.width_mm": 20.0,
                             "instances.root.params.thickness_mm": 0.3}, "PLA", 40.0, "flat_bar")
    assert thin.min_wall_ok is False

    ok = analyze_geometry({"instances.root.params.length_mm": 100.0, "instances.root.params.width_mm": 20.0,
                           "instances.root.params.thickness_mm": 5.0}, "PLA", 40.0, "flat_bar")
    assert ok.min_wall_ok is True


@needs_b123d
@needs_gmsh
def test_geometry_signature_scopes_to_the_params_actually_passed(monkeypatch):
    """Two different subsystems' signatures never collide even with an overlapping param NAME
    (thickness_mm), because the signature is computed over the caller's own dotted keys."""
    _fake_evaluate_fs(monkeypatch)
    a = analyze_geometry({"instances.root.params.length_mm": 100.0, "instances.root.params.width_mm": 20.0,
                          "instances.root.params.thickness_mm": 5.0}, "PLA", 40.0, "flat_bar")
    b = analyze_geometry({"instances.root.params.width_mm": 100.0, "instances.root.params.height_mm": 80.0,
                          "instances.root.params.thickness_mm": 3.0}, "PLA", 40.0, "panel")
    assert a.geometry_signature != b.geometry_signature
