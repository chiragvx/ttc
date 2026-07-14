"""The reusable unit of the Master Parametric Ledger.

`ParameterDef` is the single tunable-parameter type referenced by every adjustable node. It is the
load-bearing fix for two existential gaps from the analysis:
  - the original schema modelled some params as rich {value, lock_state, bounds} and others as bare
    numbers (so most params could not be locked or bounded);
  - `additionalProperties` defaulted to true, so typos forked state silently.

Here: every tunable node is a `ParameterDef`, `extra="forbid"` everywhere, and the bounds/lock
invariants are enforced at construction so an out-of-bounds or malformed parameter cannot exist.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LockState(str, Enum):
    """DYNAMIC = the AI loop may optimize it. HARD_LOCK = frozen user constraint, immune to
    automated optimization (PRD1 §2.1)."""

    DYNAMIC = "DYNAMIC"
    HARD_LOCK = "HARD_LOCK"


class ParameterDef(BaseModel):
    """A single tunable parameter: a value with a unit, a lock state, a **recommended range**, and a
    precision.

    Bounds are ADVISORY — a hint from the subsystem author about the sensible design envelope, not a
    hard cap. The copilot judges whether a request outside the recommended range is reasonable
    (grounded in the user's stated intent) and applies it with an `APPLIED_ADVISORY` status. Users
    aren't second-guessed for wanting 14 legs on a table or 20 holes on a bracket. Only HARD_LOCK
    (frozen user constraint) and physical invariants (edge-distance rule, etc.) can refuse a value.

    Invariants (enforced at construction):
      * bounds[0] <= bounds[1]   (sanity: recommended range must not be inverted)
    """

    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str
    bounds: tuple[float, float]
    lock_state: LockState = LockState.DYNAMIC
    precision: float = Field(default=1e-3, gt=0, description="round-trip tolerance, same units as value")

    @model_validator(mode="after")
    def _check_bounds(self) -> "ParameterDef":
        lo, hi = self.bounds
        if lo > hi:
            raise ValueError(f"bounds[0] ({lo}) must be <= bounds[1] ({hi})")
        return self

    def is_within_recommended(self, v: float | None = None) -> bool:
        lo, hi = self.bounds
        x = self.value if v is None else v
        return lo <= x <= hi

    @property
    def is_locked(self) -> bool:
        return self.lock_state is LockState.HARD_LOCK

    def with_value(self, new_value: float) -> "ParameterDef":
        """Return a copy with a new value. Refuses to mutate a HARD_LOCK parameter — the automated
        loop must never move a frozen user constraint."""
        if self.is_locked:
            raise ValueError("cannot change a HARD_LOCK parameter via the automated path")
        return self.model_copy(update={"value": new_value})
