"""Spike 4 kill-criterion #1: auto-mesh succeeds on >= 85% of a varied geometry set (container)."""

from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.needs_kernel

# needs build123d AND gmsh (gmsh is absent on the Windows dev box -> skip there, run in container)
_HAS_MESH = (importlib.util.find_spec("build123d") is not None
            and importlib.util.find_spec("gmsh") is not None)


@pytest.mark.skipif(not _HAS_MESH, reason="needs build123d + gmsh (Linux container)")
def test_auto_mesh_success_rate_meets_threshold():
    from packages.truth_plane.solvers.robustness import run_sweep, success_rate
    results = run_sweep(char_len=5.0)
    rate = success_rate(results)
    failed = [r.name for r in results if not r.ok]
    assert len(results) >= 18, f"expected a substantial geometry set, got {len(results)}"
    assert rate >= 0.85, f"auto-mesh success {rate:.0%} < 85% threshold; failed: {failed}"
