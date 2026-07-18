"""Closed-form valid-range computation for the interactive parameter sliders (2026-07-19).

For each of a subsystem's geometry params, the contiguous sub-range over which ALL of that
subsystem's own cross-field invariants pass, holding every OTHER param at its current value and
containing the param's current value. The frontend clamps each slider to this range so a human drag
can never land the design in a CONFLICT state (e.g. dragging `bwb_fuselage.blend_taper_mm` past
`span_mm / 2`, where its two taper zones overlap) -- the exact live failure this exists to prevent.

WHY THIS IS DIFFERENT FROM `parameter.py`'s ADVISORY BOUNDS (read before assuming this clamps the
recommended range): a ParameterDef's `bounds` are the ADVISORY recommended envelope -- deliberately
NOT a hard cap (see packages/ledger/CLAUDE.md / parameter.py: a value outside recommended still
applies, as APPLIED_ADVISORY, on copilot judgment; the "14 legs on a table" case). This module does
NOT clamp to that. It clamps to the PHYSICALLY-VALID range -- the sub-range where the subsystem's
hard cross-field invariants (edge-distance, min-wall, taper-overlap, reversed-taper, ...) actually
hold. A value can sit inside the valid range but OUTSIDE the recommended range (the slider still shows
the ⚠ advisory cue for that, computed separately on the frontend from the recommended bounds); it can
never sit outside the valid range via a drag. This keeps the advisory doctrine intact while making the
slider physically unable to produce invalid geometry.

PURE CLOSED-FORM, Tier 0: a subsystem's `invariants` callable is pure python (no OCCT, no LLM, no
solver -- see every `_check` in packages/subsystems/*.py), so this samples them freely. Measured
sub-microsecond per invariant eval, ~1 ms for a whole 11-param subsystem at this module's sample
density -- cheap enough to ride on every Tier-0 WS mutation response (packages/transport/protocol.py
CascadeUpdate.valid_ranges) so all sliders' clamps stay live as other params change, never needing a
kernel call or a separate round trip.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Optional

from packages.subsystems.base import resolve_namespace

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger
    from packages.subsystems.base import Subsystem

# How many uniform samples to walk across a param's search range looking for the invariant boundary,
# plus how many bisection steps to refine each boundary once a passing->failing transition is found.
# 128 samples + 12 bisections gives a boundary good to ~(range / 128) / 2^12 -- far finer than any
# slider step, for ~150 invariant evals/param (each sub-microsecond).
_N_SAMPLES = 128
_N_BISECT = 12


def _passes(subsystem: "Subsystem", base_values: dict[str, float], name: str, value: float) -> bool:
    """True iff EVERY invariant passes with `name` set to `value` and all other params at their
    current values. Invariants read plain attributes (`p.<name>`), so a SimpleNamespace stands in for
    the real Namespace here -- no ParameterDef machinery needed for a throwaway trial point."""
    trial = SimpleNamespace(**{**base_values, name: value})
    return not subsystem.invariants(trial)


def _valid_interval_around(
    subsystem: "Subsystem", base_values: dict[str, float], name: str,
    search_lo: float, search_hi: float, current: float,
) -> tuple[float, float]:
    """The contiguous [lo, hi] sub-interval of [search_lo, search_hi] over which every invariant
    passes AND which contains `current`. If `current` itself already violates (a pre-existing CONFLICT,
    e.g. an LLM-set value the rules validator would flag), returns the full [search_lo, search_hi]
    unclamped -- never trap the user inside a bad value they need to be able to drag OUT of."""
    if search_hi <= search_lo:
        return (search_lo, search_hi)
    if not _passes(subsystem, base_values, name, current):
        return (search_lo, search_hi)

    step = (search_hi - search_lo) / _N_SAMPLES

    def _bisect(last_ok: float, fail: float) -> float:
        """Refine a passing->failing boundary to a tight bound (last passing point)."""
        for _ in range(_N_BISECT):
            mid = (last_ok + fail) / 2.0
            if _passes(subsystem, base_values, name, mid):
                last_ok = mid
            else:
                fail = mid
        return last_ok

    def _walk(direction: int) -> float:
        """Walk from `current` by `direction*step` while invariants hold; return the last passing
        point, bisecting toward the first failing point for a tight boundary. The search BOUND itself
        is invariant-TESTED before being returned -- an untested `search_hi`/`search_lo` return was a
        real bug (2026-07-19 review): a strict-inequality invariant right at the recommended max (e.g.
        `value < spec.max`) fails exactly at the bound while every sampled point below it passes, so
        returning the bound unchecked would hand the slider a max the user could drag straight into a
        CONFLICT."""
        bound = search_hi if direction > 0 else search_lo
        last_ok = current
        x = current
        while True:
            x = x + direction * step
            past_bound = (direction > 0 and x >= bound) or (direction < 0 and x <= bound)
            if past_bound:
                # reached the search bound with no failing sample in between -- but the bound itself
                # is untested; only return it if it genuinely passes, else bisect from the last
                # in-range passing sample toward the (failing) bound.
                if _passes(subsystem, base_values, name, bound):
                    return bound
                return _bisect(last_ok, bound)
            if _passes(subsystem, base_values, name, x):
                last_ok = x
            else:
                return _bisect(last_ok, x)  # boundary between last_ok (passes) and x (fails)

    return (_walk(-1), _walk(+1))


def valid_param_ranges(
    subsystem: "Subsystem",
    ledger: "MasterParametricLedger",
    instance_id: Optional[str] = None,
) -> dict[str, tuple[float, float]]:
    """`{param_name: (valid_lo, valid_hi)}` for every geometry param of `subsystem`, computed against
    `instance_id`'s current values (default: the ledger root). See the module docstring for the
    valid-vs-advisory distinction. The search range for each param spans its recommended bounds,
    widened if needed to always include the param's CURRENT value (so an LLM-set out-of-recommended
    value stays reachable on the slider rather than being clamped away)."""
    ns = resolve_namespace(subsystem, ledger, instance_id)
    base_values = {spec.name: getattr(ns, spec.name) for spec in subsystem.params}
    out: dict[str, tuple[float, float]] = {}
    for spec in subsystem.params:
        current = base_values[spec.name]
        search_lo = min(spec.min, current)
        search_hi = max(spec.max, current)
        out[spec.name] = _valid_interval_around(
            subsystem, base_values, spec.name, search_lo, search_hi, current
        )
    return out
