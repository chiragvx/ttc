"""Derived-state resolution — how a solver verdict becomes ledger `derived.*` without being a fact.

A solver verdict is a DERIVATION of the CURRENT geometry, not a replayed user-intent fact. Each verdict
is keyed by a GEOMETRY SIGNATURE (a hash of the geometry-affecting params) plus the toolchain
fingerprint, and the current `derived` state is RESOLVED at read time from the latest matching verdict.
If the current geometry has no matching verdict (params changed since the last analysis) `derived`
stays "unknown" -> export blocked. Replay stays a pure fold over facts; derivations are resolved here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from packages.ledger.branch import iter_parameters
from packages.ledger.schema import CutFeature, DerivedSafety, MasterParametricLedger

# params that define the bracket's geometry the solver analyzes; changing any invalidates a prior
# verdict. Post-Phase-D, bracket geometry lives in the generic geometry bag under `domains.geometry.`.
GEOMETRY_PARAMS = (
    "instances.root.params.skin_thickness_mm",
    "instances.root.params.internal_rib_spacing_mm",
    "instances.root.params.plate_width_mm",
    "instances.root.params.plate_depth_mm",
    "instances.root.params.hole_diameter_mm",
)


def _cut_features_signature_payload(cut_features: tuple["CutFeature", ...]) -> list[dict]:
    """A stable, JSON-serializable representation of a cut-feature set, sorted by id so ordering never
    affects the hash. ANY change to a cut (add/remove/resize/reposition) changes this payload — the
    whole point (see `signature_from_params` below): a verdict computed against the pre-cut geometry
    must never silently keep matching the post-cut geometry."""
    return sorted((f.model_dump(mode="json") for f in cut_features), key=lambda d: d["id"])


def signature_from_params(
    params: dict[str, float],
    geometry_params: tuple[str, ...] = GEOMETRY_PARAMS,
    cut_features: tuple["CutFeature", ...] = (),
) -> str:
    """The geometry signature a verdict is keyed by. `cut_features` (default empty — every
    pre-2026-07-04 caller, and every subsystem instance with no cuts, is unaffected) folds the
    instance's subtractive features into the hash: `params` alone only covers a subsystem's own
    ParamSpec-driven dimensions, never a hole/pocket/slot added via `feature_ops` (those live on
    `Instance.cut_features`, a separate ledger field) — omitting them here would let a verdict solved
    against the UN-CUT part keep matching (and reporting as fresh/"grounded") after a cut changes the
    real geometry. See packages/truth_plane/analysis.py::analyze_geometry, the write side that computes
    this same signature over the geometry it actually solved."""
    vals: dict[str, object] = {k: params[k] for k in geometry_params if k in params}
    if cut_features:
        vals["cut_features"] = _cut_features_signature_payload(cut_features)
    return hashlib.sha256(json.dumps(vals, sort_keys=True).encode("utf-8")).hexdigest()


def geometry_signature(
    ledger: MasterParametricLedger,
    geometry_params: tuple[str, ...] | None = None,
    instance_id: str | None = None,
) -> str:
    """`geometry_params` defaults to the module constant (bracket's own params — preserves every
    pre-2026-07-03 caller unchanged). Callers analyzing a NON-bracket subsystem must pass the active
    instance's own geometry paths explicitly (e.g. `get_subsystem(instance.subsystem_type).geometry_params`
    for the root instance, or `packages.subsystems.base.geometry_paths(model, instance_id)` for any
    other instance) — otherwise the signature is computed over params that don't exist in that
    subsystem's bag and never changes, silently failing to invalidate a stale verdict.

    `instance_id` (default None -> `ledger.root_id`) selects WHICH instance's `cut_features` get folded
    into the signature — omitted entirely (matching every pre-2026-07-04 caller) only when the instance
    can't be resolved (e.g. it was removed since the verdict was cached), never fabricated as empty."""
    gp = geometry_params if geometry_params is not None else GEOMETRY_PARAMS
    iid = instance_id if instance_id is not None else ledger.root_id
    inst = ledger.instances.get(iid) if ledger.instances else None
    cut_features = tuple(inst.cut_features) if inst is not None else ()
    return signature_from_params(
        {p: pd.value for p, pd in iter_parameters(ledger)},
        geometry_params=gp,
        cut_features=cut_features,
    )


@dataclass
class Verdict:
    geometry_signature: str
    fingerprint: str
    factor_of_safety: float | None
    mesh_converged: bool
    watertight: bool
    min_wall_ok: bool
    # The LOAD CASE this verdict was actually solved against. Without these, a verdict cache keyed
    # only on geometry+toolchain can be served back for a different (material, load_n) request than
    # the one that produced it — a grounded-LOOKING FS for a case the solver never actually ran
    # (e.g. /optimize's 25 N verdict silently satisfying a later /analyze at 40 N). `latest_verdict`
    # below requires an exact match on both before treating a cached verdict as current.
    material: str = "PLA"
    load_n: float = 40.0
    solver_seconds: float = 0.0

    def to_derived(self) -> DerivedSafety:
        return DerivedSafety(
            factor_of_safety=self.factor_of_safety, mesh_converged=self.mesh_converged,
            watertight=self.watertight, min_wall_ok=self.min_wall_ok,
        )


def latest_verdict(
    ledger: MasterParametricLedger,
    verdicts: list[Verdict],
    *,
    fingerprint: str,
    geometry_params: tuple[str, ...] | None = None,
    instance_id: str | None = None,
    material: str | None = None,
    load_n: float | None = None,
) -> Verdict | None:
    """The newest verdict matching the CURRENT geometry (INCLUDING any cut_features on `instance_id`,
    default the root instance) + toolchain, or None (stale / never analyzed).

    `material`/`load_n` (default None -> match ANY case, preserving pre-existing callers that don't
    yet track a specific load case) restrict this to a verdict solved against THAT exact load case.
    Pass the case being asked about whenever one is known — omitting it is what let a verdict solved
    at one (material, load_n) get served back as "grounded" for a different requested case (e.g.
    /optimize's 25 N verdict silently satisfying a later /analyze at 40 N)."""
    sig = geometry_signature(ledger, geometry_params=geometry_params, instance_id=instance_id)
    for v in reversed(verdicts):
        if v.geometry_signature != sig or v.fingerprint != fingerprint:
            continue
        if material is not None and v.material != material:
            continue
        if load_n is not None and v.load_n != load_n:
            continue
        return v
    return None


def resolve_derived(
    ledger: MasterParametricLedger,
    verdicts: list[Verdict],
    *,
    fingerprint: str,
    geometry_params: tuple[str, ...] | None = None,
    instance_id: str | None = None,
    material: str | None = None,
    load_n: float | None = None,
) -> DerivedSafety:
    v = latest_verdict(ledger, verdicts, fingerprint=fingerprint, geometry_params=geometry_params,
                       instance_id=instance_id, material=material, load_n=load_n)
    return v.to_derived() if v else DerivedSafety()  # empty -> all None -> unknown -> blocked


def ledger_with_derived(
    ledger: MasterParametricLedger,
    verdicts: list[Verdict],
    *,
    fingerprint: str,
    geometry_params: tuple[str, ...] | None = None,
    instance_id: str | None = None,
    material: str | None = None,
    load_n: float | None = None,
) -> MasterParametricLedger:
    derived = resolve_derived(ledger, verdicts, fingerprint=fingerprint, geometry_params=geometry_params,
                              instance_id=instance_id, material=material, load_n=load_n)
    return ledger.model_copy(update={"derived": derived})
