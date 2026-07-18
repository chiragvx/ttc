"""Coupling resolver (Phase 2, 2026-07-19) — walk the ledger's couplings and DERIVE each target's load
from its registered relation, or return `"unknown"` when it can't be grounded (relation not in the
catalog, a missing/unresolvable input). Pure arithmetic; NO OCCT/LLM/solver.

This is the honest core: a coupling whose relation isn't registered, or whose input can't be resolved,
yields a result with `value=None` and a `reason` — never a fabricated number. Downstream (the load
path / export gate) treats a `None`-valued coupling target the same way it treats an unknown FS: it
blocks the green light. `"unknown blocks export"` extended from safety scalars to derived loads.

v1 is a DAG evaluated in one pass over `ledger.couplings`; a source that is itself the output of
another coupling is NOT chained yet (a later increment) — a coupling input sources a part PARAM or a
literal duty value only."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from packages.couplings.relations import RELATION_REGISTRY


def _norm_unit(u: str) -> str:
    """Normalize a unit label for comparison: lowercase, drop spaces and '^', map ²/³ to 2/3. So
    'mm^2', 'mm2', 'mm²' all compare equal, but 'mm' (length) vs 'mm2' (area) does NOT — which is the
    real mis-wiring this catches."""
    return (u or "").lower().replace(" ", "").replace("^", "").replace("²", "2").replace("³", "3")

if TYPE_CHECKING:
    from packages.ledger.schema import Coupling, MasterParametricLedger


@dataclass(frozen=True)
class CouplingResult:
    """The outcome of resolving ONE coupling. `value is None` == "unknown" (with `reason`), which must
    block a grounded claim, never be treated as 0 or a pass."""

    coupling_id: str
    target_instance: str
    relation: str
    value: Optional[float]           # the derived output (e.g. force_n); None == unknown
    unit: Optional[str]              # the output unit label when known
    output_quantity: Optional[str]   # e.g. "force_n"
    reason: Optional[str] = None     # why it's unknown, when value is None

    @property
    def is_known(self) -> bool:
        return self.value is not None


def _resolve_input(ledger: "MasterParametricLedger", inp, expected_unit: str) -> tuple[Optional[float], Optional[str]]:
    """(value, reason) for one CouplingInput — a literal, or a part-param lookup. reason is set only
    when the value can't be resolved. A param-sourced input whose unit CLEARLY differs from the
    relation's declared input unit (e.g. sourcing a length `mm` param where the relation wants an area
    `mm^2`) is a mis-wiring -> unknown, not a silently-wrong number (2026-07-19 review). A literal has
    no unit to check (the LLM states it in the relation's declared unit by construction)."""
    if inp.value is not None:
        return float(inp.value), None
    inst = ledger.instances.get(inp.from_instance)
    if inst is None:
        return None, f"source instance {inp.from_instance!r} does not exist"
    pd = inst.params.get(inp.from_param)
    if pd is None:
        return None, f"{inp.from_instance!r} has no param {inp.from_param!r}"
    if pd.unit and expected_unit and _norm_unit(pd.unit) != _norm_unit(expected_unit):
        return None, (f"unit mismatch: {inp.from_instance!r}.{inp.from_param!r} is in {pd.unit!r} but "
                      f"the relation expects {expected_unit!r} — wire a source in the right unit")
    return float(pd.value), None


def resolve_coupling(ledger: "MasterParametricLedger", coupling: "Coupling") -> CouplingResult:
    rel = RELATION_REGISTRY.get(coupling.relation)
    if rel is None:
        return CouplingResult(coupling.id, coupling.target_instance, coupling.relation, None, None, None,
                              reason=f"relation {coupling.relation!r} is not in the catalog — the load "
                                     f"is UNKNOWN (it must be grounded by a registered relation, never "
                                     f"assumed)")
    if coupling.target_instance not in ledger.instances:
        return CouplingResult(coupling.id, coupling.target_instance, coupling.relation, None, None, None,
                              reason=f"target instance {coupling.target_instance!r} does not exist")
    # gather inputs the relation declares
    values: dict[str, float] = {}
    for name in rel.inputs:
        if name not in coupling.inputs:
            return CouplingResult(coupling.id, coupling.target_instance, coupling.relation, None,
                                  rel.output[1], rel.output[0],
                                  reason=f"relation {rel.name!r} needs input {name!r}, none wired")
        v, why = _resolve_input(ledger, coupling.inputs[name], rel.inputs[name])
        if v is None:
            return CouplingResult(coupling.id, coupling.target_instance, coupling.relation, None,
                                  rel.output[1], rel.output[0],
                                  reason=f"input {name!r}: {why}")
        values[name] = v
    try:
        out = rel.evaluate(values)
    except Exception as e:  # a relation that blows up on real inputs is unknown, not a crash
        return CouplingResult(coupling.id, coupling.target_instance, coupling.relation, None,
                              rel.output[1], rel.output[0], reason=f"relation evaluation failed: {e}")
    # A non-finite result (NaN/inf) is NEVER a grounded load — it must be "unknown", never fed to FS as
    # if valid (2026-07-19 review, CRITICAL: this is the fabricated-green-light path). A negative
    # magnitude is likewise a mis-wiring for these v1 relations (all produce >= 0 from sane inputs).
    if not math.isfinite(out) or out < 0.0:
        return CouplingResult(coupling.id, coupling.target_instance, coupling.relation, None,
                              rel.output[1], rel.output[0],
                              reason=f"relation produced a non-physical value ({out}) — UNKNOWN, not a "
                                     f"grounded load (check the wired inputs)")
    return CouplingResult(coupling.id, coupling.target_instance, coupling.relation, float(out),
                          rel.output[1], rel.output[0])


def resolve_couplings(ledger: "MasterParametricLedger") -> list[CouplingResult]:
    """Every coupling resolved, in ledger order. A target with NO coupling simply isn't present."""
    return [resolve_coupling(ledger, c) for c in ledger.couplings]


def coupling_gate_findings(ledger: "MasterParametricLedger") -> tuple[list[str], list[str]]:
    """`(reasons, unknowns)` for the export gate — extends "unknown blocks export" from safety scalars
    to DERIVED LOADS. A coupling that can't be grounded (relation not in the catalog, missing input)
    means the target's load is unknown, so any FS computed for it would be for a fabricated load — that
    must block export, exactly like an unknown FS does. Injected via `evaluate_export_gates`'s
    `extra_findings` seam (combined with the discipline findings at the app's gate call sites)."""
    reasons: list[str] = []
    unknowns: list[str] = []
    for res in resolve_couplings(ledger):
        if not res.is_known:
            unknowns.append(f"coupling:{res.coupling_id}")
            reasons.append(f"coupling {res.coupling_id} -> {res.target_instance} load is unknown: {res.reason}")
    return reasons, unknowns


def derived_load_n(ledger: "MasterParametricLedger", instance_id: str) -> tuple[Optional[float], Optional[str]]:
    """(force_n, reason) — the DERIVED applied load on `instance_id`, the SUPERPOSITION (sum) of every
    force coupling targeting it, or (None, reason) if ANY of them is unknown, or (None, None) if the
    part has no force coupling. Summing is the physically-correct combination of co-located force loads
    — an earlier version returned only the FIRST and silently dropped the rest (non-conservative;
    2026-07-19 review). This is the seam the existing load-threading (`effective_load_n`) extends: a
    coupled part's load is a graph output, not a stated scalar. Only `force_n`-output relations feed the
    structural load path; a torque/moment coupling is carried but not (yet) consumed as a cantilever FS
    load."""
    targeting = [r for r in resolve_couplings(ledger) if r.target_instance == instance_id]
    # ANY unknown coupling on this part makes its load unknown — an UNKNOWN relation has no known
    # output quantity, so we cannot rule out that it contributes force; treating it as absent would
    # under-report the load and let a fabricated-green-light through (2026-07-19 review). A KNOWN
    # non-force coupling (torque/moment) is carried but not consumed as a structural force load.
    for r in targeting:
        if not r.is_known:
            return None, r.reason
    force_results = [r for r in targeting if r.output_quantity == "force_n"]
    if not force_results:
        return None, None  # no force coupling on this part (any non-force ones are all known here)
    return sum(r.value for r in force_results), None
