"""Phase 1 proof-point: the hero-bracket vertical slice runs end-to-end and the export gate flips
BLOCKED -> ELIGIBLE only once a grounded FS + sign-off exist (container)."""

from __future__ import annotations

import importlib.util
import shutil

import pytest

pytestmark = [pytest.mark.needs_kernel, pytest.mark.needs_solver]

_HAS_KERNEL = importlib.util.find_spec("build123d") is not None
_HAS_CCX = shutil.which("ccx") is not None


@pytest.fixture(scope="module")
def report():
    if not (_HAS_KERNEL and _HAS_CCX):
        pytest.skip("needs build123d + ccx (Linux container)")
    from packages.transport.app import make_demo_ledger
    from packages.truth_plane.demo_pipeline import run_hero_pipeline
    return run_hero_pipeline(make_demo_ledger(), load_n=40.0)


def test_generator_emitted_tags(report):
    assert "plate.body" in report.tags
    assert sum(1 for t in report.tags if t.startswith("hole[")) == 4


def test_estimate_and_fs_are_grounded(report):
    assert report.print_time_s > 0 and report.material_g > 0
    assert report.fs_status == "OK"
    assert report.factor_of_safety is not None and report.factor_of_safety >= 1.5


def test_export_gate_flips_only_after_grounded_fs(report):
    assert report.export_before == "EXPORT_BLOCKED"   # FS unknown -> blocked
    assert report.export_after == "EXPORT_ELIGIBLE"    # FS + sign-off + validity -> eligible
