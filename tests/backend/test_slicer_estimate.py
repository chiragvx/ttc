"""Analytic print estimator + supportless-overhang check."""

from __future__ import annotations

import math

from packages.truth_plane.solvers.slicer_estimate import estimate_print, overhang_supportless_ok


def test_print_estimate_hand_computed():
    est = estimate_print(10000.0, "PLA", infill_frac=0.2, wall_fraction=0.25, volumetric_flow_mm3_s=5.0)
    # solid_frac = 0.25 + 0.75*0.2 = 0.40 -> mat_vol = 4000 mm3
    assert math.isclose(est.material_volume_mm3, 4000.0)
    assert math.isclose(est.material_g, 1.24e-3 * 4000.0, rel_tol=1e-6)
    assert math.isclose(est.print_time_s, 800.0)
    assert est.is_estimate is True  # never the export-gate number


def test_overhang_check():
    assert overhang_supportless_ok(45.0) is True
    assert overhang_supportless_ok(60.0) is False
