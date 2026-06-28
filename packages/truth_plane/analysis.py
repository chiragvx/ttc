"""The grounded analysis — render the current geometry, run CalculiX FS, return a typed Verdict.

Kernel/solver-bound (build123d + gmsh + CalculiX), so imports are lazy: this module loads on the
Windows dev box, but `analyze_geometry` only runs in the Linux runtime. The Verdict it returns is what
the derived-resolver turns into ledger `derived.*` state.
"""

from __future__ import annotations

import os
import tempfile
import time

from packages.ledger.apply import MIN_WALL_MM
from packages.ledger.derived_resolver import Verdict, signature_from_params
from packages.ledger.fingerprint import fingerprint
from packages.ledger.nodes import SKIN


def analyze_geometry(params: dict[str, float], material_name: str, load_n: float) -> Verdict:
    from packages.ledger.bom import material
    from packages.truth_plane.regen.export import export_part  # noqa: F401 (kept for parity)
    from packages.truth_plane.regen.generator import export_step_text
    from packages.truth_plane.regen.templated import render_bracket
    from packages.truth_plane.solvers.fs import evaluate_fs

    skin = params[SKIN]
    part = render_bracket(width_mm=60.0, depth_mm=40.0, thickness_mm=max(1.0, skin), hole_dia_mm=6.0, n_holes=4)
    watertight = bool(part.solid.is_valid())

    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(export_step_text(part.solid))
        mat = material(material_name)
        t0 = time.monotonic()
        v = evaluate_fs(path, youngs_mod_mpa=mat.youngs_mod_mpa, poisson=mat.poisson,
                        yield_mpa=mat.yield_mpa, tip_load_n=load_n, char_lens=(4.0, 3.0))
        dt = time.monotonic() - t0
    finally:
        os.remove(path)

    ok = v.status == "OK"
    return Verdict(
        geometry_signature=signature_from_params(params),
        fingerprint=fingerprint(),
        factor_of_safety=v.factor_of_safety if ok else None,
        mesh_converged=ok,
        watertight=watertight,
        min_wall_ok=skin >= MIN_WALL_MM,
        solver_seconds=round(dt, 2),
    )
