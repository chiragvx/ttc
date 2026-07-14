"""Branching & invariant-aware 3-way merge of the parametric ledger.

The correct safety stance (grafted from the analysis): scalar bounded parameters merge automatically,
but merging must PRESERVE invariants — CRDT/last-writer-wins convergence guarantees structural
consistency, NOT semantic safety, so a merge that would break bounds / HARD_LOCK / a coupled invariant
is surfaced as a CONFLICT rather than silently applied. Geometry/topology merges are never auto-applied
(they land as an AI-proposed diff elsewhere); here we resolve the scalar parameter state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from packages.ledger.apply import _set, check_invariants
from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import MasterParametricLedger


def iter_parameters(model: BaseModel, prefix: str = ""):
    """Yield (dotted_path, ParameterDef) for every tunable leaf in the ledger.
    Handles typed BaseModel blocks, dict-of-ParameterDef bags (e.g. `Domains.geometry`), AND the
    instance tree introduced in Phase G (`instances.<id>.params.<name>`)."""
    for name, value in model:
        path = f"{prefix}{name}"
        if isinstance(value, ParameterDef):
            yield path, value
        elif isinstance(value, BaseModel):
            yield from iter_parameters(value, path + ".")
        elif isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, ParameterDef):
                    yield f"{path}.{k}", v
                elif isinstance(v, BaseModel):
                    # Phase G: `instances: dict[str, Instance]` — descend into each named instance.
                    yield from iter_parameters(v, f"{path}.{k}.")


def _set_param(ledger: MasterParametricLedger, path: str, pd: ParameterDef) -> None:
    parts = path.split(".")
    obj = ledger
    for p in parts[:-1]:
        obj = obj[p] if isinstance(obj, dict) else getattr(obj, p)
    _set(obj, parts[-1], pd)


@dataclass
class MergeConflict:
    path: str
    base: float
    ours: float
    theirs: float
    reason: str


@dataclass
class MergeResult:
    merged: MasterParametricLedger
    conflicts: list[MergeConflict] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.conflicts


def merge_ledgers(base: MasterParametricLedger, ours: MasterParametricLedger,
                  theirs: MasterParametricLedger) -> MergeResult:
    merged = base.model_copy(deep=True)
    conflicts: list[MergeConflict] = []

    b = dict(iter_parameters(base))
    o = dict(iter_parameters(ours))
    t = dict(iter_parameters(theirs))

    for path, bpd in b.items():
        opd, tpd = o[path], t[path]
        bv, ov, tv = bpd.value, opd.value, tpd.value
        # sticky lock: HARD_LOCK on either side wins
        lock = LockState.HARD_LOCK if (opd.is_locked or tpd.is_locked) else bpd.lock_state

        if ov == bv and tv == bv:
            chosen = bv
        elif ov != bv and tv == bv:
            chosen = ov
        elif tv != bv and ov == bv:
            chosen = tv
        elif ov == tv:                       # both changed the same way
            chosen = ov
        else:                                # both changed differently -> conflict
            conflicts.append(MergeConflict(path, bv, ov, tv, "both branches changed this parameter"))
            chosen = bv                      # leave base value pending resolution

        _set_param(merged, path, bpd.model_copy(update={"value": chosen, "lock_state": lock}))

    # invariant-aware: a structurally-valid merge that breaks a coupled invariant is a conflict
    for violation in check_invariants(merged):
        conflicts.append(MergeConflict("<invariant>", 0.0, 0.0, 0.0, violation))

    return MergeResult(merged=merged, conflicts=conflicts)
