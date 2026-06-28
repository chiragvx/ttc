"""The grounded analysis — render the current geometry, run CalculiX FS, return a typed Verdict.

Kernel/solver-bound (build123d + gmsh + CalculiX), so imports are lazy: this module loads on the
Windows dev box, but `analyze_geometry` only runs in the Linux runtime. The Verdict it returns is what
the derived-resolver turns into ledger `derived.*` state.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import tempfile
import time
import traceback

from packages.ledger.apply import MIN_WALL_MM
from packages.ledger.derived_resolver import Verdict, signature_from_params
from packages.ledger.fingerprint import fingerprint
from packages.ledger.nodes import DEPTH, HOLE_DIA, SKIN, WIDTH


def analyze_geometry(params: dict[str, float], material_name: str, load_n: float) -> Verdict:
    from packages.ledger.bom import material
    from packages.truth_plane.regen.export import export_part  # noqa: F401 (kept for parity)
    from packages.truth_plane.regen.generator import export_step_text
    from packages.truth_plane.regen.templated import render_bracket
    from packages.truth_plane.solvers.fs import evaluate_fs

    skin = params[SKIN]
    # tunable geometry; defaults preserve any old single-param callers
    hole_dia = params.get(HOLE_DIA, 6.0)
    width = params.get(WIDTH, 60.0)
    depth = params.get(DEPTH, 40.0)
    part = render_bracket(width_mm=width, depth_mm=depth, thickness_mm=max(1.0, skin),
                          hole_dia_mm=hole_dia, n_holes=4)
    watertight = bool(part.solid.is_valid)  # build123d exposes is_valid as a property, not a method

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


def _worker(q, params, material_name, load_n):
    try:
        q.put(("ok", analyze_geometry(params, material_name, load_n)))
    except Exception:
        q.put(("error", traceback.format_exc()))


# --- optimization: the sanctioned 3-variant sweep -> the lightest design that passes FS ---
def _plate_mass_g(mat, base_params, skin):
    # structural plate mass = density * footprint area * skin thickness (thinner = lighter, monotone)
    area = base_params.get(WIDTH, 60.0) * base_params.get(DEPTH, 40.0)
    return round(mat.density_g_per_mm3 * area * skin, 1)


def _run_optimize(candidates, base_params, material_name, load_n, fs_floor):
    from packages.ledger.bom import material
    mat = material(material_name)
    variants = []
    best_skin = None
    best_verdict = None
    for skin in candidates:
        # the sweep varies skin only; every other geometry param is held at the current design so the
        # swept verdict's signature matches the ledger (else best_verdict would never resolve into derived)
        v = analyze_geometry({**base_params, SKIN: skin}, material_name, load_n)
        fs = v.factor_of_safety
        feasible = fs is not None and fs >= fs_floor
        mass = _plate_mass_g(mat, base_params, skin)
        variants.append({"skin": skin, "fs": round(fs, 2) if fs is not None else None,
                         "mass_g": mass, "feasible": feasible})
        if feasible and (best_skin is None or skin < best_skin):  # lightest feasible = thinnest passing
            best_skin, best_verdict = skin, v
    best_mass = _plate_mass_g(mat, base_params, best_skin) if best_skin else None
    return {"variants": variants, "best_skin": best_skin, "best_mass_g": best_mass, "best_verdict": best_verdict}


def _optimize_worker(q, candidates, base_params, material_name, load_n, fs_floor):
    try:
        q.put(("ok", _run_optimize(candidates, base_params, material_name, load_n, fs_floor)))
    except Exception:
        q.put(("error", traceback.format_exc()))


def optimize_in_subprocess(candidates: list[float], base_params: dict, material_name: str,
                           load_n: float, fs_floor: float, timeout_s: float = 600.0) -> dict:
    """Sweep skin candidates (each a real CalculiX FS) in a child process; return the variants + the
    lightest one that passes the FS floor. base_params carries the rest of the current geometry (rib,
    hole, plate dims) held fixed across the sweep. Runs in a child so gmsh gets a main thread."""
    ctx = mp.get_context("spawn")  # spawn: clean child (safe from a Dramatiq worker; runs gmsh in a main thread)
    q: mp.Queue = ctx.Queue()
    p = ctx.Process(target=_optimize_worker, args=(q, candidates, base_params, material_name, load_n, fs_floor))
    p.start()
    try:
        status, payload = q.get(timeout=timeout_s)
    except queue.Empty:
        p.terminate()
        raise RuntimeError("optimize timed out") from None
    finally:
        p.join(10)
    if status == "error":
        raise RuntimeError(payload)
    return payload


def analyze_in_subprocess(params: dict[str, float], material_name: str, load_n: float,
                          timeout_s: float = 300.0) -> Verdict:
    """Run the analysis in a child PROCESS so gmsh gets a main thread (it installs a signal handler,
    which fails inside a threadpool / Dramatiq worker thread). Used by both the inline endpoint and
    the queued actor."""
    ctx = mp.get_context("spawn")  # spawn: clean child (safe from a Dramatiq worker; runs gmsh in a main thread)
    q: mp.Queue = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q, params, material_name, load_n))
    p.start()
    try:
        status, payload = q.get(timeout=timeout_s)
    except queue.Empty:
        p.terminate()
        raise RuntimeError("analysis timed out") from None
    finally:
        p.join(10)
    if status == "error":
        raise RuntimeError(payload)
    return payload
