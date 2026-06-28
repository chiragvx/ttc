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
from packages.ledger.schema import DerivedSafety, MasterParametricLedger

# params that define the geometry the solver analyzes; changing any invalidates a prior verdict
GEOMETRY_PARAMS = (
    "domains.structure.skin_thickness_mm",
    "domains.structure.internal_rib_spacing_mm",
    "domains.structure.plate_width_mm",        # footprint changes the FEA + mass -> invalidates the verdict
    "domains.structure.plate_depth_mm",
    "domains.manufacturing.hole_diameter_mm",  # hole size changes the FEA stress field -> invalidates the verdict
)


def signature_from_params(params: dict[str, float]) -> str:
    vals = {k: params[k] for k in GEOMETRY_PARAMS if k in params}
    return hashlib.sha256(json.dumps(vals, sort_keys=True).encode("utf-8")).hexdigest()


def geometry_signature(ledger: MasterParametricLedger) -> str:
    return signature_from_params({p: pd.value for p, pd in iter_parameters(ledger)})


@dataclass
class Verdict:
    geometry_signature: str
    fingerprint: str
    factor_of_safety: float | None
    mesh_converged: bool
    watertight: bool
    min_wall_ok: bool
    solver_seconds: float = 0.0

    def to_derived(self) -> DerivedSafety:
        return DerivedSafety(
            factor_of_safety=self.factor_of_safety, mesh_converged=self.mesh_converged,
            watertight=self.watertight, min_wall_ok=self.min_wall_ok,
        )


def latest_verdict(ledger: MasterParametricLedger, verdicts: list[Verdict], *, fingerprint: str) -> Verdict | None:
    """The newest verdict matching the CURRENT geometry + toolchain, or None (stale / never analyzed)."""
    sig = geometry_signature(ledger)
    for v in reversed(verdicts):
        if v.geometry_signature == sig and v.fingerprint == fingerprint:
            return v
    return None


def resolve_derived(ledger: MasterParametricLedger, verdicts: list[Verdict], *, fingerprint: str) -> DerivedSafety:
    v = latest_verdict(ledger, verdicts, fingerprint=fingerprint)
    return v.to_derived() if v else DerivedSafety()  # empty -> all None -> unknown -> blocked


def ledger_with_derived(ledger: MasterParametricLedger, verdicts: list[Verdict], *, fingerprint: str) -> MasterParametricLedger:
    return ledger.model_copy(update={"derived": resolve_derived(ledger, verdicts, fingerprint=fingerprint)})
