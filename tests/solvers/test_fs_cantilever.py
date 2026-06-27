"""Spike 4 validation: the OCCT->gmsh->CalculiX FS pipeline against a closed-form cantilever.

The oracle is Euler-Bernoulli beam theory (tip deflection PL^3/3EI), NOT an FEA run. Deflection is
the primary check because it is convergent and non-singular; if the C3D10 node ordering, BCs,
material, load, or .frd parsing were wrong, deflection would not match. Runs only where ccx is
present (the Linux container), skipped on the Windows dev box.
"""

from __future__ import annotations

import importlib.util
import shutil
import tempfile

import pytest

pytestmark = [pytest.mark.needs_kernel, pytest.mark.needs_solver]

_HAS_KERNEL = importlib.util.find_spec("build123d") is not None
_HAS_CCX = shutil.which("ccx") is not None


@pytest.fixture(scope="module")
def cantilever_result():
    if not (_HAS_KERNEL and _HAS_CCX):
        pytest.skip("needs build123d + ccx (Linux container)")
    from packages.truth_plane.regen.generator import export_step_text
    from packages.truth_plane.solvers.cases import Cantilever
    from packages.truth_plane.solvers.fs import evaluate_fs

    c = Cantilever(length_mm=100, width_mm=10, height_mm=10,
                   youngs_mod_mpa=210000, poisson=0.3, yield_mpa=250, tip_load_n=100)
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False, mode="w") as f:
        f.write(export_step_text(c.solid()))
        path = f.name
    verdict = evaluate_fs(path, youngs_mod_mpa=c.youngs_mod_mpa, poisson=c.poisson,
                          yield_mpa=c.yield_mpa, tip_load_n=c.tip_load_n)
    return c, verdict


def test_tip_deflection_matches_closed_form(cantilever_result):
    c, v = cantilever_result
    analytic = c.analytical_tip_deflection_mm
    err = abs(v.tip_deflection_mm - analytic) / analytic
    assert err < 0.03, f"tip deflection {v.tip_deflection_mm:.4f} vs analytic {analytic:.4f} ({err:.1%})"


def test_fs_pipeline_converges(cantilever_result):
    _, v = cantilever_result
    assert v.status == "OK", f"expected converged FS, got {v.status}: {v.notes}"
    assert v.converged and v.stress_drift_pct is not None and v.stress_drift_pct <= 10.0


def test_fs_is_physically_reasonable(cantilever_result):
    c, v = cantilever_result
    # FEA peak von Mises >= nominal beam stress (mild clamp concentration), so FS <= analytical FS.
    ratio = v.factor_of_safety / c.analytical_fs
    assert 0.8 <= ratio <= 1.05, f"FEA FS {v.factor_of_safety:.2f} vs analytic {c.analytical_fs:.2f} (ratio {ratio:.2f})"


def test_mesh_refines_monotonically(cantilever_result):
    _, v = cantilever_result
    counts = [lvl.n_nodes for lvl in v.levels]
    assert counts == sorted(counts) and counts[0] < counts[-1], f"mesh did not refine: {counts}"
