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


# Output quantities from the relation catalog (packages/couplings/relations.py) that represent a
# genuine LOAD-BEARING claim on the TARGET instance — i.e. a physical force/moment/torque actually
# APPLIED to that part (a "solicitation"), as distinct from:
#   * a computed RESULT of some load already applied (stress_mpa, shear_stress_mpa, deflection_mm) —
#     these describe how the part responds to a load, they are not themselves a demand on it, so
#     coupling one onto a target is NOT a load-bearing claim (the 2026-07-19/07-31 precedent this
#     preserves: a part whose ONLY coupling outputs stress_mpa/deflection_mm must not be blocked);
#   * a pure SECTION/GEOMETRIC property (moment_of_inertia_mm4, polar_moment_mm4) — these describe the
#     part's own cross-section (consumed as an INPUT by other relations), never a load on it;
#   * a CAPACITY/allowable (critical_load_n, the Euler buckling threshold a column can withstand
#     before it fails) — a limit the design must stay under, not a demand placed on it.
#
# Of the load-bearing set, only "force_n" is directly consumable by the structural (cantilever
# tip-force) load path `derived_load_n` feeds. "torque_nmm"/"moment_nmm" (a twisting/bending moment
# actually applied to the part) and "preload_n" (a bolt/joint preload — a real applied force, just not
# spelled "force_n") are KNOWN load-bearing claims the force-only path CANNOT consume — treating that
# the same as "no coupling at all" would silently solve/export against a load with NO relationship to
# the part's actual physics (Defect 1, 2026-08-03: a moment/torque coupling used to fall out of the
# `output_quantity == "force_n"` filter below and vanish, indistinguishable from an uncoupled part —
# the real solver then ran a case against a hardcoded fallback load and the export gate saw nothing
# wrong with it). Deliberately an EXPLICIT allowlist, not an implicit "anything that isn't a known
# non-load quantity" guess — this must be revisited by hand every time relations.py grows a new output
# quantity, so an unclassified future addition defaults to NOT load-bearing (uncounted, but also not
# mis-blocking) until a human actually triages it, exactly like an unregistered relation name defaults
# to "unknown" rather than being guessed at.
LOAD_BEARING_OUTPUT_QUANTITIES = frozenset({"force_n", "torque_nmm", "moment_nmm", "preload_n"})

# Of the load-bearing set above, this is the subset the force-only structural load path can actually
# turn into a number today.
_FORCE_CONSUMABLE_OUTPUT_QUANTITIES = frozenset({"force_n"})


def _unconsumed_reason(instance_id: str, unconsumed: list["CouplingResult"]) -> str:
    names = ", ".join(f"{r.coupling_id} ({r.output_quantity})" for r in unconsumed)
    return (f"{instance_id!r} carries a load-bearing coupling the structural force-only path cannot "
           f"consume: {names} — solving against a fallback force would have no relationship to this "
           f"part's actual applied load")


def coupling_gate_findings(
    ledger: "MasterParametricLedger", instance_id: str | None = None,
) -> tuple[list[str], list[str]]:
    """`(reasons, unknowns)` for the export gate — extends "unknown blocks export" from safety scalars
    to DERIVED LOADS. A coupling that can't be grounded (relation not in the catalog, missing input)
    means the target's load is unknown, so any FS computed for it would be for a fabricated load — that
    must block export, exactly like an unknown FS does. Injected via `evaluate_export_gates`'s
    `extra_findings` seam (combined with the discipline findings at the app's gate call sites).

    2026-08-03 (Defect 1): a coupling can also be fully KNOWN (resolved to a real number) yet still be
    something the structural force-only path cannot consume — a torque/moment/preload claim, per
    `LOAD_BEARING_OUTPUT_QUANTITIES`'s own comment. When a target has NO force_n contribution at all,
    that is NOT "no coupling" either: a real FS computed for this part while ignoring that load has no
    relationship to what the part actually carries, so it blocks here too, at the SAME severity as an
    unknown FS input. But when the SAME target ALSO has a real, known force_n contribution (from a
    different coupling), that force is used and this is NOT blocked — a coexisting torque/moment is a
    real but SEPARATE multi-load-case combination question (a human-wall item, matching
    `_iter_coarse_cantilever_fs`'s own longstanding "prefer force, don't double-count/conflict"
    precedent in packages/transport/app.py), not a fabricated-load question; over-blocking a part with
    a perfectly real, non-fabricated derived force would be its own bug.

    `instance_id` (default None -> every coupling, the pre-existing behavior) restricts this to
    couplings TARGETING that instance — an unrelated part's ungrounded coupling elsewhere in the file
    must not block a different, fully-grounded part's export (foundations-audit H3, 2026-07-21)."""
    reasons: list[str] = []
    unknowns: list[str] = []
    all_results = resolve_couplings(ledger)
    # targets with at least one KNOWN, real force_n contribution — see the docstring note above on why
    # this takes precedence over a coexisting unconsumed torque/moment/preload claim on the same part.
    has_force = {r.target_instance for r in all_results if r.is_known and r.output_quantity == "force_n"}
    for res in all_results:
        if instance_id is not None and res.target_instance != instance_id:
            continue
        if not res.is_known:
            unknowns.append(f"coupling:{res.coupling_id}")
            reasons.append(f"coupling {res.coupling_id} -> {res.target_instance} load is unknown: {res.reason}")
        elif (res.output_quantity in LOAD_BEARING_OUTPUT_QUANTITIES
              and res.output_quantity not in _FORCE_CONSUMABLE_OUTPUT_QUANTITIES
              and res.target_instance not in has_force):
            unknowns.append(f"coupling:{res.coupling_id}")
            reasons.append(
                f"coupling {res.coupling_id} -> {res.target_instance} derives a {res.output_quantity} "
                f"load ({res.value:.3g} {res.unit}) that the structural force-only path cannot consume "
                f"— a computed FS for this part would ignore a load it actually carries")
    return reasons, unknowns


def derived_load_n(ledger: "MasterParametricLedger", instance_id: str) -> tuple[Optional[float], Optional[str]]:
    """(force_n, reason) — the DERIVED applied load on `instance_id`, the SUPERPOSITION (sum) of every
    force coupling targeting it, or (None, reason) if ANY of them is unknown, or (None, None) if the
    part has no force coupling. Summing is the physically-correct combination of co-located force loads
    — an earlier version returned only the FIRST and silently dropped the rest (non-conservative;
    2026-07-19 review). This is the seam the existing load-threading (`effective_load_n`) extends: a
    coupled part's load is a graph output, not a stated scalar. Only `force_n`-output relations feed the
    structural load path — a REAL, known force_n contribution is always preferred/used the moment one
    exists (matches `_iter_coarse_cantilever_fs`'s own longstanding "prefer force, don't double-count/
    conflict with a bending-moment reading" precedent, packages/transport/app.py).

    2026-08-03 (Defect 1): when a target has NO force_n contribution at all, a KNOWN torque/moment/
    preload coupling (see `LOAD_BEARING_OUTPUT_QUANTITIES`) now returns `(None, reason)` —
    distinguishable from `(None, None)` ("no coupling at all") — instead of silently vanishing through
    the `force_n` filter below. Before this, a moment/torque-ONLY coupling was indistinguishable here
    from an uncoupled part, so `effective_load_n` fell through to its fabricated default and a real
    solver FS got computed against a load with no relationship to the part's actual (unconsumed) load
    claim, while the export gate saw a fully-populated, seemingly-valid result. `coupling_gate_findings`
    is the actual enforcement point that blocks export on this; this function's job is just to make the
    two cases distinguishable so a caller (or a human reading the reason) can tell them apart."""
    targeting = [r for r in resolve_couplings(ledger) if r.target_instance == instance_id]
    # ANY unknown coupling on this part makes its load unknown — an UNKNOWN relation has no known
    # output quantity, so we cannot rule out that it contributes force; treating it as absent would
    # under-report the load and let a fabricated-green-light through (2026-07-19 review).
    for r in targeting:
        if not r.is_known:
            return None, r.reason
    # a real, known force_n contribution is ALWAYS used the moment one exists — see this function's own
    # docstring on why a coexisting unconsumed torque/moment/preload does not override it.
    force_results = [r for r in targeting if r.output_quantity == "force_n"]
    if force_results:
        return sum(r.value for r in force_results), None
    # NO force contribution — but a KNOWN load-bearing coupling this force-only path can't consume
    # (torque/moment/preload) still blocks, distinguishably from "no coupling at all" (see docstring).
    unconsumed = [r for r in targeting
                  if r.output_quantity in LOAD_BEARING_OUTPUT_QUANTITIES
                  and r.output_quantity not in _FORCE_CONSUMABLE_OUTPUT_QUANTITIES]
    if unconsumed:
        return None, _unconsumed_reason(instance_id, unconsumed)
    return None, None  # no coupling at all (any non-force ones present are all non-load-bearing)
