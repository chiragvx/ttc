"""3-variant parametric sweep — the sanctioned optimizer for the wedge.

The cut-list bans NSGA-II ("use a 3-variant sweep"): evaluate a handful of variants with the REAL
grounded pipeline and pick the lightest one that meets the FS floor. No surrogate, no Pareto archive —
just honest brute force over a few points, every number from CalculiX. Coarser mesh than the
validation gate (this is comparative, not a certification).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from packages.ledger.bom import material
from packages.truth_plane.regen.generator import export_step_text
from packages.truth_plane.regen.templated import render_bracket
from packages.truth_plane.solvers.slicer_estimate import estimate_print


@dataclass
class Variant:
    param_value: float
    factor_of_safety: float | None
    mass_g: float
    print_time_s: float
    feasible: bool


def sweep_bracket_thickness(thicknesses: list[float], *, material_name: str, load_n: float,
                            fs_floor: float, width_mm: float = 60.0, depth_mm: float = 40.0,
                            hole_dia_mm: float = 6.0, n_holes: int = 4) -> list[Variant]:
    from packages.truth_plane.solvers.fs import evaluate_fs  # lazy: pulls gmsh (Linux-only)

    mat = material(material_name)
    variants: list[Variant] = []
    for t in thicknesses:
        part = render_bracket(width_mm=width_mm, depth_mm=depth_mm, thickness_mm=t,
                              hole_dia_mm=hole_dia_mm, n_holes=n_holes)
        vol = part.solid.volume
        fd, path = tempfile.mkstemp(suffix=".step")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(export_step_text(part.solid))
            verdict = evaluate_fs(path, youngs_mod_mpa=mat.youngs_mod_mpa, poisson=mat.poisson,
                                  yield_mpa=mat.yield_mpa, tip_load_n=load_n, char_lens=(4.0, 3.0))
        finally:
            os.remove(path)
        fs = verdict.factor_of_safety
        feasible = verdict.status == "OK" and fs is not None and fs >= fs_floor
        variants.append(Variant(t, fs, mat.density_g_per_mm3 * vol,
                                estimate_print(vol, material_name).print_time_s, feasible))
    return variants


def pick_lightest_feasible(variants: list[Variant]) -> Variant | None:
    feasible = [v for v in variants if v.feasible]
    return min(feasible, key=lambda v: v.mass_g) if feasible else None
