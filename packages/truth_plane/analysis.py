"""The grounded analysis — render the current geometry, run CalculiX FS, return a typed Verdict.

Kernel/solver-bound (build123d + gmsh + CalculiX), so imports are lazy: this module loads on the
Windows dev box, but `analyze_geometry` only runs in the Linux runtime. The Verdict it returns is what
the derived-resolver turns into ledger `derived.*` state.

2026-07-03 — generalized past bracket-only: `analyze_geometry` now builds geometry via the SUBSYSTEM
REGISTRY (any registered part), not a hardcoded `render_bracket` call. Whether a part actually gets a
real FS number is gated by `Subsystem.fea_eligible` (opt-in per part — see packages/subsystems/base.py)
plus a runtime single-solid check: only parts sharing the SAME validated cantilever methodology
(clamp one end, load the other; packages/truth_plane/solvers/{mesh,fs}.py) get a solved FS. Every other
part (compounds, cylindrical/rotational parts, anything not explicitly vetted) returns a well-formed
Verdict with `factor_of_safety=None` — honestly "unknown", never a fabricated number. This is
Inversion #1 applied to the whole catalog, not just the original hero part.
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


def _plain_params(params: dict[str, float]) -> dict[str, float]:
    """Strip the `instances.<id>.params.` prefix off every dotted key -> plain ParamSpec names."""
    return {k.rsplit(".", 1)[-1]: v for k, v in params.items()}


def _min_wall_ok(resolved_plain: dict[str, float]) -> bool:
    """Generic min-wall floor: every param whose name ends in `thickness_mm` (the load-bearing
    wall/skin lever for every currently fea_eligible subsystem) must clear the FDM floor. True when
    the subsystem has no thickness-named param at all (nothing to violate)."""
    thickness_like = [v for k, v in resolved_plain.items() if k.endswith("thickness_mm")]
    return all(v >= MIN_WALL_MM for v in thickness_like) if thickness_like else True


def _n_solids(solid) -> int:
    try:
        bodies = list(solid.solids())
    except AttributeError:
        return 1
    return len(bodies) if bodies else 1


def _coerce_cut_features(raw) -> tuple:
    """Normalize `cut_features` to a tuple of real `CutFeature` objects, accepting either already-typed
    `CutFeature`s (the in-process/spawn-subprocess call path, where pickle carries pydantic objects
    fine) or plain JSON dicts (the durable Dramatiq/Redis actor path — `packages/truth_plane/jobs.py`'s
    actors go over a JSON-encoded broker, so the ledger's cut_features are serialized to dicts before
    `.send()`). Centralizing this here means every downstream consumer (`apply_cut_features`,
    `swept_volume_mm3`, the signature hash) always sees the real typed model, regardless of transport."""
    from packages.ledger.schema import CutFeature
    return tuple(cf if isinstance(cf, CutFeature) else CutFeature.model_validate(cf) for cf in (raw or ()))


def analyze_geometry(params: dict[str, float], material_name: str, load_n: float,
                     subsystem_name: str = "bracket", cut_features: "list | None" = None) -> Verdict:
    """Build `subsystem_name`'s geometry from `params` (dotted-path keyed, e.g.
    `instances.root.params.skin_thickness_mm` — any prefix works, only the trailing param name is
    read) and, IF that subsystem is FEA-eligible AND its build produced a single solid (defense in
    depth — a compound assembly never gets a fabricated load case even if mis-flagged), run the
    validated Gmsh+CalculiX cantilever pipeline. Otherwise return a Verdict with `factor_of_safety`
    left `None` — the honest "unknown" this whole design is built around.

    `subsystem_name` defaults to "bracket" so every pre-2026-07-03 caller (a bare
    `{SKIN: .., RIB: ..}`-style params dict, no subsystem argument) is unaffected.

    `cut_features` (2026-07-04, default None -> no cuts, every pre-2026-07-04 caller unaffected) is
    the target instance's `Instance.cut_features` list. This is REQUIRED for Inversion #1: without it,
    this function solves the FS of the UN-CUT geometry while the ledger, mesh, and STEP export all
    show the cut part — a stale, wrong-but-confident "grounded" verdict for any part that had a hole
    added or removed after it was last analyzed. Applying the SAME `apply_cut_features` the registered
    `geometry_builder` uses (packages/subsystems/__init__.py's `_build` closure) keeps this pipeline's
    geometry identical to what `/mesh` and `/export/step` actually produce."""
    from packages.ledger.bom import material
    from packages.ledger.parameter import ParameterDef
    from packages.subsystems import get_subsystem_model
    from packages.subsystems.base import Namespace
    from packages.truth_plane.regen.generator import export_step_text

    sub = get_subsystem_model(subsystem_name)
    cuts = _coerce_cut_features(cut_features)

    plain = _plain_params(params)
    resolved = {p.name: ParameterDef(value=plain.get(p.name, p.value), unit=p.unit, bounds=(p.min, p.max))
               for p in sub.params}

    if sub.build is None:
        # Assembly-template subsystem (2026-07-03 — see packages/subsystems/assembly_template.py):
        # this master node has NO geometry of its own to build/check — its children carry the real
        # solids, and this pure-params entry point isn't ledger-aware (no instance tree to resolve
        # children from). Honest "unknown" FS, same as any other non-eligible part — never a
        # fabricated single-solid check. `watertight=True` because there is no geometry here to be
        # INVALID (nothing built, nothing to fail a validity check on) — distinct from an actually
        # broken build, which would leave `watertight=False`.
        sig = signature_from_params(params, geometry_params=tuple(params.keys()), cut_features=cuts)
        resolved_plain = {name: pd.value for name, pd in resolved.items()}
        return Verdict(
            geometry_signature=sig, fingerprint=fingerprint(),
            factor_of_safety=None, mesh_converged=False, watertight=True,
            min_wall_ok=_min_wall_ok(resolved_plain), solver_seconds=0.0,
        )

    part = sub.build(Namespace(resolved))
    sig = signature_from_params(params, geometry_params=tuple(params.keys()), cut_features=cuts)
    resolved_plain = {name: pd.value for name, pd in resolved.items()}
    min_wall_ok = _min_wall_ok(resolved_plain)

    if cuts:
        from packages.subsystems.cut_features import apply_cut_features
        try:
            part = apply_cut_features(part, list(cuts))
        except ValueError:
            # the cut(s) sever the part into more than one island — a real fabrication error, not
            # something FEA can honestly run on (the validated cantilever methodology assumes ONE
            # solid). Same "honest unknown" as any other non-single-solid geometry below, never a
            # fabricated FS on a part that can't physically hold together as drawn.
            return Verdict(
                geometry_signature=sig, fingerprint=fingerprint(),
                factor_of_safety=None, mesh_converged=False, watertight=False,
                min_wall_ok=min_wall_ok, solver_seconds=0.0,
            )

    watertight = bool(part.solid.is_valid)  # build123d exposes is_valid as a property, not a method

    eligible = sub.fea_eligible and _n_solids(part.solid) == 1
    if not eligible:
        return Verdict(
            geometry_signature=sig, fingerprint=fingerprint(),
            factor_of_safety=None, mesh_converged=False, watertight=watertight,
            min_wall_ok=min_wall_ok, solver_seconds=0.0,
        )

    from packages.truth_plane.solvers.fs import evaluate_fs

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
        geometry_signature=sig,
        fingerprint=fingerprint(),
        factor_of_safety=v.factor_of_safety if ok else None,
        mesh_converged=ok,
        watertight=watertight,
        min_wall_ok=min_wall_ok,
        solver_seconds=round(dt, 2),
    )


def _worker(q, params, material_name, load_n, subsystem_name, cut_features):
    try:
        q.put(("ok", analyze_geometry(params, material_name, load_n, subsystem_name, cut_features)))
    except Exception:
        q.put(("error", traceback.format_exc()))


# --- optimization: the sanctioned 3-variant sweep -> the lightest design that passes FS ---
def _thickness_param_name(sub):
    """The generic "sweep target" for optimize — the mass-driving wall/skin thickness. Returns the
    name of `sub`'s one param ending in `thickness_mm` (the same convention `_min_wall_ok` relies on),
    or None if the subsystem has no such param — meaning optimize is simply not offered for it."""
    for p in sub.params:
        if p.name.endswith("thickness_mm"):
            return p.name
    return None


def _mass_g_for(sub, dotted_params, material_name, thickness_name, thickness_value, cut_features=()):
    """Generic mass helper: resolve `sub`'s own params (dotted `dotted_params` overridden with the
    swept thickness) into a Namespace and get the volume from the subsystem's OWN `.volume` function —
    no bracket-specific area formula. Mirrors the Namespace-construction pattern in `analyze_geometry`.

    `cut_features` (default empty — every pre-2026-07-04 caller unaffected) subtracts each feature's
    analytic swept volume, the SAME formula the registered subsystem's `_volume` closure uses
    (packages/subsystems/__init__.py) — without this, a swept part's optimize-sweep mass telemetry
    silently ignores any hole/pocket/slot on it, the same class of bug `analyze_geometry` itself was
    fixed for on the FS side."""
    from packages.ledger.bom import material
    from packages.ledger.parameter import ParameterDef
    from packages.subsystems.base import Namespace
    plain = {k.rsplit(".", 1)[-1]: v for k, v in dotted_params.items()}
    plain[thickness_name] = thickness_value
    ns = Namespace({p.name: ParameterDef(value=plain.get(p.name, p.value), unit=p.unit, bounds=(p.min, p.max))
                    for p in sub.params})
    vol = sub.volume(ns) if sub.volume else 0.0
    cuts = _coerce_cut_features(cut_features)
    if cuts:
        from packages.subsystems.cut_features import swept_volume_mm3
        vol = max(0.0, vol - sum(swept_volume_mm3(f) for f in cuts))
    return round(material(material_name).density_g_per_mm3 * vol, 1)


def _run_optimize(subsystem_name, candidates, base_params, material_name, load_n, fs_floor, cut_features=()):
    """Sweep `subsystem_name`'s own thickness-like param (whichever `_thickness_param_name` finds) —
    generalized past bracket's hardcoded skin_thickness_mm sweep to any fea_eligible subsystem."""
    from packages.subsystems import get_subsystem_model
    sub = get_subsystem_model(subsystem_name)
    thickness_name = _thickness_param_name(sub)
    if thickness_name is None:
        return {"variants": [], "best_value": None, "best_mass_g": None, "best_verdict": None, "param_name": None}
    thickness_key = next((k for k in base_params if k.rsplit(".", 1)[-1] == thickness_name), None)
    variants = []
    best_value = None
    best_verdict = None
    for t in candidates:
        # the sweep varies thickness only; every other geometry param is held at the current design so
        # the swept verdict's signature matches the ledger (else best_verdict would never resolve into derived)
        params = {**base_params, thickness_key: t} if thickness_key else dict(base_params)
        v = analyze_geometry(params, material_name, load_n, subsystem_name, cut_features)
        fs = v.factor_of_safety
        feasible = fs is not None and fs >= fs_floor
        mass = _mass_g_for(sub, base_params, material_name, thickness_name, t, cut_features)
        variants.append({"value": t, "fs": round(fs, 2) if fs is not None else None,
                         "mass_g": mass, "feasible": feasible})
        if feasible and (best_value is None or t < best_value):  # lightest feasible = thinnest passing
            best_value, best_verdict = t, v
    best_mass = (_mass_g_for(sub, base_params, material_name, thickness_name, best_value, cut_features)
                if best_value is not None else None)
    return {"variants": variants, "best_value": best_value, "best_mass_g": best_mass,
            "best_verdict": best_verdict, "param_name": thickness_name}


def _optimize_worker(q, candidates, base_params, material_name, load_n, fs_floor, subsystem_name, cut_features):
    try:
        q.put(("ok", _run_optimize(subsystem_name, candidates, base_params, material_name, load_n, fs_floor,
                                   cut_features)))
    except Exception:
        q.put(("error", traceback.format_exc()))


def optimize_in_subprocess(candidates: list[float], base_params: dict, material_name: str,
                           load_n: float, fs_floor: float, timeout_s: float = 600.0,
                           subsystem_name: str = "bracket", cut_features: "list | None" = None) -> dict:
    """Sweep thickness candidates (each a real CalculiX FS) in a child process; return the variants +
    the lightest one that passes the FS floor. base_params carries the rest of the current geometry
    held fixed across the sweep. Runs in a child so gmsh gets a main thread. `subsystem_name` defaults
    to "bracket" so every pre-2026-07-03 caller (5 positional args, no subsystem) is unaffected.
    `cut_features` (default None -> no cuts) is threaded into every swept `analyze_geometry` call and
    the mass telemetry, same rationale as `analyze_geometry`'s own docstring."""
    ctx = mp.get_context("spawn")  # spawn: clean child (safe from a Dramatiq worker; runs gmsh in a main thread)
    q: mp.Queue = ctx.Queue()
    p = ctx.Process(target=_optimize_worker,
                    args=(q, candidates, base_params, material_name, load_n, fs_floor, subsystem_name,
                         tuple(cut_features or ())))
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
                          subsystem_name: str = "bracket", timeout_s: float = 300.0,
                          cut_features: "list | None" = None) -> Verdict:
    """Run the analysis in a child PROCESS so gmsh gets a main thread (it installs a signal handler,
    which fails inside a threadpool / Dramatiq worker thread). Used by both the inline endpoint and
    the queued actor. `subsystem_name` defaults to "bracket" — every pre-2026-07-03 caller (3
    positional args, no subsystem) is unaffected. `cut_features` (default None -> no cuts) is the
    target instance's `Instance.cut_features` — see `analyze_geometry`'s docstring for why this must
    be threaded through for Inversion #1."""
    ctx = mp.get_context("spawn")  # spawn: clean child (safe from a Dramatiq worker; runs gmsh in a main thread)
    q: mp.Queue = ctx.Queue()
    p = ctx.Process(target=_worker, args=(q, params, material_name, load_n, subsystem_name,
                                          tuple(cut_features or ())))
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
