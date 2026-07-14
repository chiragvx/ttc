"""Shared taper + station-sampling math for lofted-body subsystems (`lofted_spindle`, `lofted_hull`,
`ogive_fuselage`). Pure python — NO build123d import — so the (fast) interactive-plane closed-form
volume integrals and the (kernel) loft-station placement both call the exact same formula and can
never silently drift apart. Not a Subsystem itself; just the shared arithmetic these files import.
"""

from __future__ import annotations

import math

_EPS_MM = 1e-9


def ease_at(x: float, x_a: float, x_b: float, length: float,
            start_val: float, max_val: float, end_val: float) -> float:
    """Cosine-smoothstep interpolation of ONE scalar dimension along an axis in `[0, length]`:
    `start_val` at `x=0` -> `max_val` (held flat across the `[x_a, x_b]` plateau) -> `end_val` at
    `x=length`. Dimension-agnostic — callers pass already-halved radii/half-widths/half-heights, or
    any other per-station scalar that should ease the same way (that's what lets `lofted_spindle`'s
    radius schedule and `lofted_hull`'s independent width/height-top/height-bottom schedules reuse
    this ONE formula instead of three near-identical copies).
    """
    if x_a > _EPS_MM and x <= x_a:
        t = x / x_a
        ease = 0.5 - 0.5 * math.cos(math.pi * t)
        return start_val + (max_val - start_val) * ease
    if (length - x_b) > _EPS_MM and x >= x_b:
        t = (x - x_b) / (length - x_b)
        ease = 0.5 - 0.5 * math.cos(math.pi * t)
        return max_val + (end_val - max_val) * ease
    return max_val


def ogive_ease_at(x: float, x_a: float, x_b: float, length: float,
                   start_val: float, max_val: float, end_val: float,
                   power: float = 0.5) -> float:
    """Power-law taper, measured from EACH TIP inward: `t = (distance from that zone's own tip) /
    (that zone's own taper-zone length)`, value = `tip_val + (max_val - tip_val) * t**power`.

    Deliberately NOT `ease_at`'s cosine smoothstep. `ease_at` has ZERO slope at every boundary —
    tip included — so a taper zone starts out nearly flat right at the tip before curving up: fine
    (correct, even) for a bottle's shoulder-into-a-neck or a tool handle's blunt end, but exactly
    the "squished bottle" artifact a real aircraft nose/tail must NOT have — a fuselage nose flares
    away from its tip immediately (an ogive/paraboloid), and a tailcone narrows to a real point at
    the end rather than lingering at a constant "neck" radius first (see `ogive_fuselage.py`'s
    module docstring, diagnosed directly from a rendered screenshot this session: `lofted_spindle`
    reused as-is for a fuselage produced a visible flat cylindrical neck at both tips).

    `power < 1` (the default, 0.5, the classic "tangent ogive"/half-power nose-cone profile) makes
    `t**power` rise steeply for small `t` — near-vertical right at the tip, flattening smoothly as
    `t -> 1` (zero net crease at the plateau boundary is NOT guaranteed the way `ease_at` guarantees
    it — the derivative at t=1 is exactly `power`, not 0 — but a visible parting line where a nose
    fairing meets the constant-diameter barrel is realistic, not a defect). `power == 1` degenerates
    to a plain linear cone; `power > 1` is concave (a thin pin-like taper) — not the intended use,
    but not blocked, since a user might explicitly want a needle-sharp look.

    Same drop-in (x, x_a, x_b, length, start_val, max_val, end_val) signature as `ease_at` (only the
    trailing `power` kwarg is new) so any caller already parameterized around `ease_at`'s taper-zone
    convention can swap directly — see `ogive_fuselage.py`'s `_width_at`/`_height_at`."""
    if x_a > _EPS_MM and x <= x_a:
        t = x / x_a  # 0 at the nose tip (x=0), 1 at the plateau boundary
        return start_val + (max_val - start_val) * (t ** power)
    if (length - x_b) > _EPS_MM and x >= x_b:
        t = (length - x) / (length - x_b)  # 0 at the tail tip (x=length), 1 at the plateau boundary
        return end_val + (max_val - end_val) * (t ** power)
    return max_val


def zone_samples(x0: float, x1: float, n: int) -> list[float]:
    """`n` evenly-spaced sample positions across `[x0, x1]`; collapses to a single sample if the
    zone has ~zero length (a 0mm taper)."""
    if x1 - x0 <= _EPS_MM:
        return [x1]
    return [x0 + (x1 - x0) * i / (n - 1) for i in range(n)]


def taper_stations(length: float, start_taper: float, end_taper: float, n_taper_stations: int) -> list[float]:
    """Axial sample positions (`x`) for a start-taper / plateau / end-taper zone layout: dense
    sampling through each taper zone (for the smooth-loft station list), a single plateau-boundary
    sample in between, deduplicated where a zero-length taper zone collapses onto the plateau
    boundary. Shared by every lofted-body subsystem's outer/inner-loft station list."""
    x_a = start_taper
    x_b = length - end_taper
    xs = zone_samples(0.0, x_a, n_taper_stations)
    if x_b - x_a > _EPS_MM:
        xs.append(x_b)
    end_xs = zone_samples(x_b, length, n_taper_stations)
    if xs and abs(end_xs[0] - xs[-1]) < _EPS_MM:
        xs += end_xs[1:]
    else:
        xs += end_xs
    return xs
