"""Unit coverage for the 2026-07-21 audit fix in `packages/truth_plane/solvers/calculix.py::solve`.

BUG: `solve()` ran `ccx` via `subprocess.run(...)` with no `check=True` and never inspected
`proc.returncode` -- the only gates were "did a .frd file get written" and "is the parsed
displacement dict non-empty." A CalculiX run that fails (singular stiffness matrix, negative
Jacobian, a solver warning) but still writes a syntactically valid, parseable-but-degenerate .frd
was indistinguishable from a real converged solve -- a live threat to the "never emit a PASS on an
unconverged mesh" rule in `packages/truth_plane/CLAUDE.md`.

This mocks `subprocess.run` so it needs no real `ccx` binary. It DOES need `gmsh` importable: unlike
the closed-form validation in test_fs_cantilever.py, this only touches the `Mesh` dataclass shape
(never calls a gmsh function), but `calculix.py` imports `Mesh` from `solvers/mesh.py`, which imports
`gmsh` unconditionally at module scope -- same `needs_gmsh` situation test_analysis_multi_subsystem.py
documents for its own mocked-solver tests. Skipped on the Windows dev box; runs wherever gmsh is
importable (the Linux kernel container).
"""

from __future__ import annotations

import importlib.util
import os

import pytest

pytestmark = pytest.mark.needs_solver

_HAS_GMSH = importlib.util.find_spec("gmsh") is not None
needs_gmsh = pytest.mark.skipif(not _HAS_GMSH, reason="needs gmsh importable (calculix.py imports Mesh from mesh.py)")


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _degenerate_but_parseable_frd() -> str:
    """A syntactically valid .frd with a real DISP block -- exactly the "plausible but wrong" output
    a singular/non-converged ccx run can still leave behind. Field layout matches
    calculix.py::_parse_frd: tag in cols[0:3], node id in cols[3:13], then 12-char value chunks."""
    disp_vals = f"{-1.0:12.5E}{-2.0:12.5E}{-3.0:12.5E}"
    return " -4  DISP\n" f" -1{1:10d}{disp_vals}\n" " -3\n"


def _minimal_mesh():
    from packages.truth_plane.solvers.mesh import Mesh
    return Mesh(nodes={1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)}, tets10=[],
               face_nodes={"fixed": {1}, "load": {2}}, char_len=1.0)


@needs_gmsh
def test_solve_raises_on_nonzero_ccx_returncode_even_with_a_parseable_frd(monkeypatch):
    """The core regression: before the fix, a non-zero rc with a parseable .frd sailed through as a
    real SolveResult. It must now surface as a solver failure instead."""
    import packages.truth_plane.solvers.calculix as calculix_module

    def _fake_run(cmd, cwd, capture_output, text, timeout):
        # Simulate ccx: it failed, but (as CalculiX can) still left a parseable .frd from a
        # partial/degenerate solve -- the exact scenario a bare "did a .frd get written" check
        # cannot catch.
        with open(os.path.join(cwd, "job.frd"), "w", encoding="utf-8") as fh:
            fh.write(_degenerate_but_parseable_frd())
        return _FakeCompletedProcess(returncode=1, stdout="*ERROR in e_c3d: zero pivot\n")

    monkeypatch.setattr(calculix_module.subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="rc=1"):
        calculix_module.solve(_minimal_mesh(), youngs_mod_mpa=210000, poisson=0.3, tip_load_n=100.0)


@needs_gmsh
def test_solve_raises_on_error_in_output_even_with_returncode_zero(monkeypatch):
    """CalculiX is known to sometimes exit 0 despite printing a fatal *ERROR rather than propagating
    a non-zero return code -- the returncode check alone would miss this, so solve() must also treat
    a *ERROR in ccx's own output as a solver failure."""
    import packages.truth_plane.solvers.calculix as calculix_module

    def _fake_run(cmd, cwd, capture_output, text, timeout):
        with open(os.path.join(cwd, "job.frd"), "w", encoding="utf-8") as fh:
            fh.write(_degenerate_but_parseable_frd())
        return _FakeCompletedProcess(returncode=0, stdout="*ERROR in e_c3d: zero pivot\n")

    monkeypatch.setattr(calculix_module.subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match=r"\*ERROR"):
        calculix_module.solve(_minimal_mesh(), youngs_mod_mpa=210000, poisson=0.3, tip_load_n=100.0)


@needs_gmsh
def test_solve_still_succeeds_on_a_clean_zero_returncode_run(monkeypatch):
    """Regression guard for the fix: a genuinely clean run (rc=0, no *ERROR, a real .frd with both
    DISP and STRESS) must still produce a normal SolveResult -- the new gates must not be so strict
    they start rejecting good solves."""
    import packages.truth_plane.solvers.calculix as calculix_module

    disp_vals = f"{-1.0:12.5E}{-2.0:12.5E}{-3.0:12.5E}"
    stress_vals = "".join(f"{v:12.5E}" for v in (10.0, 5.0, 2.0, 1.0, 0.5, 0.2))
    clean_frd = (
        " -4  DISP\n"
        f" -1{1:10d}{disp_vals}\n"
        " -3\n"
        " -4  STRESS\n"
        f" -1{1:10d}{stress_vals}\n"
        " -3\n"
    )

    def _fake_run(cmd, cwd, capture_output, text, timeout):
        with open(os.path.join(cwd, "job.frd"), "w", encoding="utf-8") as fh:
            fh.write(clean_frd)
        return _FakeCompletedProcess(returncode=0, stdout="CalculiX finished\n")

    monkeypatch.setattr(calculix_module.subprocess, "run", _fake_run)

    result = calculix_module.solve(_minimal_mesh(), youngs_mod_mpa=210000, poisson=0.3, tip_load_n=100.0)
    assert result.n_nodes == 2
    assert result.max_von_mises_mpa > 0
