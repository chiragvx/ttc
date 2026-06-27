"""3-variant parametric sweep: FS monotone in thickness, picks the lightest feasible (container)."""

from __future__ import annotations

import importlib.util
import shutil

import pytest

from packages.truth_plane.solvers.sweep import Variant, pick_lightest_feasible

pytestmark = [pytest.mark.needs_kernel, pytest.mark.needs_solver]

_HAS = importlib.util.find_spec("build123d") is not None and shutil.which("ccx") is not None


@pytest.fixture(scope="module")
def variants():
    if not _HAS:
        pytest.skip("needs build123d + ccx (Linux container)")
    from packages.truth_plane.solvers.sweep import sweep_bracket_thickness
    return sweep_bracket_thickness([6.0, 8.0, 10.0], material_name="PLA", load_n=120.0, fs_floor=1.5)


def test_fs_increases_with_thickness(variants):
    fs = [v.factor_of_safety for v in variants]
    assert fs == sorted(fs) and fs[0] < fs[-1]


def test_mass_increases_with_thickness(variants):
    mass = [v.mass_g for v in variants]
    assert mass == sorted(mass)


def test_picks_lightest_feasible(variants):
    best = pick_lightest_feasible(variants)
    assert best is not None and best.param_value == 8.0  # thinnest meeting FS >= 1.5


def test_pick_returns_none_when_all_infeasible():
    synthetic = [Variant(t, 1.0, 10.0 * t, 100.0 * t, feasible=False) for t in (6.0, 8.0, 10.0)]
    assert pick_lightest_feasible(synthetic) is None
