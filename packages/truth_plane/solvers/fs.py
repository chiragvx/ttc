"""Factor-of-safety evaluation with a mesh-convergence study -> a typed verdict.

This is the Spike 4 core: a hands-off OCCT(STEP) -> gmsh -> CalculiX pipeline that returns a grounded
FS *with* a convergence check, or "UNKNOWN" (which blocks export) when it cannot certify the number.
A PASS is never emitted on an unconverged mesh. The FS scalar comes from CalculiX, never an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.truth_plane.solvers.calculix import SolveResult, solve
from packages.truth_plane.solvers.mesh import mesh_step

# default clamp-min-x / load-max-x cantilever-style selection
DEFAULT_FACES = {"fixed": (0, False), "load": (0, True)}


@dataclass
class FsVerdict:
    status: str                       # "OK" | "UNKNOWN"
    factor_of_safety: float | None
    max_von_mises_mpa: float | None
    tip_deflection_mm: float | None
    converged: bool
    stress_drift_pct: float | None    # |finest - coarser| / finest, last two levels
    levels: list[SolveResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def evaluate_fs(
    step_path: str,
    *,
    youngs_mod_mpa: float,
    poisson: float,
    yield_mpa: float,
    tip_load_n: float,
    char_lens: tuple[float, ...] = (5.0, 3.0, 2.0),
    drift_tol_pct: float = 10.0,
    face_selectors: dict[str, tuple[int, bool]] | None = None,
) -> FsVerdict:
    faces = face_selectors or DEFAULT_FACES
    levels: list[SolveResult] = []
    for cl in char_lens:
        m = mesh_step(step_path, char_len=cl, face_selectors=faces)
        levels.append(solve(m, youngs_mod_mpa=youngs_mod_mpa, poisson=poisson, tip_load_n=tip_load_n))

    notes: list[str] = []
    if len(levels) < 2:
        return FsVerdict("UNKNOWN", None, None, None, False, None, levels, ["need >=2 refinement levels"])

    vm_finest = levels[-1].max_von_mises_mpa
    vm_prev = levels[-2].max_von_mises_mpa
    drift = abs(vm_finest - vm_prev) / vm_finest * 100.0 if vm_finest else float("inf")
    converged = drift <= drift_tol_pct

    if vm_finest != vm_finest:  # NaN -> no stress parsed
        return FsVerdict("UNKNOWN", None, None, levels[-1].tip_disp_z_mm, False, None, levels,
                         ["no stress field parsed"])
    if not converged:
        notes.append(f"stress not converged: drift {drift:.1f}% > {drift_tol_pct}% — FS is UNKNOWN")
        return FsVerdict("UNKNOWN", None, vm_finest, levels[-1].tip_disp_z_mm, False, drift, levels, notes)

    fs = yield_mpa / vm_finest
    notes.append(f"converged: stress drift {drift:.1f}% over last refinement")
    return FsVerdict("OK", fs, vm_finest, levels[-1].tip_disp_z_mm, True, drift, levels, notes)
