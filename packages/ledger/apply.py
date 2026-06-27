"""The rules validator — applies a ParameterDelta to the ledger deterministically (NOT an LLM).

The LLM only proposes a `ParameterDelta`; THIS code decides what happens to the source of truth:
  * forbidden target (derived.* / review.*)            -> REJECTED
  * unknown / non-tunable node                          -> REJECTED
  * HARD_LOCK parameter                                 -> REJECTED (frozen user constraint)
  * value outside bounds                                -> CLAMPED to the safe window
  * a coupled cross-field invariant would break         -> CONFLICT (no change applied)
  * otherwise                                           -> APPLIED

Schema enforces SHAPE; this enforces INVARIANTS. Returns a NEW ledger (event-sourcing style) + a
typed outcome; the original is never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from packages.ledger.deltas import ParameterDelta, is_forbidden_target
from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import MasterParametricLedger

MIN_WALL_MM = 0.8  # a representative coupled manufacturing invariant


class ApplyStatus(str, Enum):
    APPLIED = "APPLIED"
    CLAMPED = "CLAMPED"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"


@dataclass
class ApplyOutcome:
    status: ApplyStatus
    target: str
    old_value: float | None = None
    new_value: float | None = None
    message: str = ""

    @property
    def changed(self) -> bool:
        return self.status in (ApplyStatus.APPLIED, ApplyStatus.CLAMPED)


def _resolve(ledger: MasterParametricLedger, path: str):
    """Return (parent_obj, attr_name, current_value) for a dotted path, or (None, None, None)."""
    parts = path.split(".")
    obj = ledger
    for p in parts[:-1]:
        if not hasattr(obj, p):
            return None, None, None
        obj = getattr(obj, p)
    last = parts[-1]
    if not hasattr(obj, last):
        return None, None, None
    return obj, last, getattr(obj, last)


def check_invariants(ledger: MasterParametricLedger) -> list[str]:
    """Cross-field invariants that no single delta may break."""
    out: list[str] = []
    skin = ledger.domains.structure.skin_thickness_mm
    if skin.value < MIN_WALL_MM:
        out.append(f"skin_thickness {skin.value} < min wall {MIN_WALL_MM}")
    return out


def apply_delta(ledger: MasterParametricLedger, delta: ParameterDelta) -> tuple[MasterParametricLedger, ApplyOutcome]:
    target = delta.target_node
    if is_forbidden_target(target):
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, message="LLM may not write derived/review nodes")

    parent, attr, current = _resolve(ledger, target)
    if parent is None or not isinstance(current, ParameterDef):
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, message="unknown or non-tunable node")

    if current.is_locked:
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, old_value=current.value,
                                    message="HARD_LOCK parameter is frozen")

    lo, hi = current.bounds
    requested = delta.requested_value
    clamped = min(max(requested, lo), hi)
    was_clamped = clamped != requested

    new_ledger = ledger.model_copy(deep=True)
    n_parent, _, n_pd = _resolve(new_ledger, target)
    updated = n_pd.with_value(clamped)
    if delta.set_lock is not None:
        updated = updated.model_copy(update={"lock_state": LockState(delta.set_lock)})
    setattr(n_parent, attr, updated)

    violations = check_invariants(new_ledger)
    if violations:
        return ledger, ApplyOutcome(ApplyStatus.CONFLICT, target, old_value=current.value,
                                    new_value=clamped, message="; ".join(violations))

    status = ApplyStatus.CLAMPED if was_clamped else ApplyStatus.APPLIED
    msg = f"clamped {requested} -> {clamped} into [{lo}, {hi}]" if was_clamped else ""
    return new_ledger, ApplyOutcome(status, target, old_value=current.value, new_value=clamped, message=msg)
