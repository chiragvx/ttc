"""Shared NACA 4-digit SYMMETRIC airfoil profile math (mirrors `_loft_profiles.py`'s role for
`lofted_spindle`/`lofted_hull`): pure python, NO build123d import, so both the (fast) interactive-
plane closed-form area/volume integrals and the (kernel) loft-station point generation call the
exact same formula and can never silently drift apart. Not a Subsystem itself; `naca_wing.py`
imports this.

THE FORMULA (NACA 4-digit thickness distribution, symmetric — e.g. NACA0012 at thickness_pct=12.0):
    yt(x) = 5*t*c*(0.2969*sqrt(x/c) - 0.1260*(x/c) - 0.3516*(x/c)^2 + 0.2843*(x/c)^3 + A4*(x/c)^4)
    where t = thickness_pct/100, c = chord, x in [0, c].

CLOSED-TRAILING-EDGE CHOICE (the one deliberate deviation from the textbook coefficients — read
before touching A4): the canonical/"open-TE" coefficient is A4 = -0.1015, which leaves
yt(x=c) = 5*t*c*(0.2969-0.1260-0.3516+0.2843-0.1015) = 0.0021*t*c > 0 for any real t,c — i.e. the
upper and lower surfaces do NOT meet at the trailing edge, they leave a small but real open gap.
Feeding that into a periodic-spline closed profile (the exact `bd.Spline(*pts, periodic=True)` +
`bd.Wire`/`bd.Face` technique `lofted_hull.py`'s module docstring documents, and the one used below)
would force the spline to jump across that gap, risking exactly the kind of "looks watertight,
`is_valid` may still say True, but isn't a clean closed loop" pitfall that file's docstring warns
about. This module instead uses the well-known CLOSED-TRAILING-EDGE variant, A4 = -0.1036, which
forces yt(c) == 0.0 EXACTLY (0.2969-0.1260-0.3516+0.2843-0.1036 = 0.0 to float precision — verified
directly below and in tests/subsystems/test_naca_wing.py) — a genuinely closed, non-degenerate loop
with no post-hoc clamp/hack needed on the last point. This is a standard, widely-documented NACA
variant (not a novel derivation), chosen here specifically because it is provably closed rather than
merely "close enough".

LOCAL AXIS CONVENTION — read this before calling `naca4_profile_points` anywhere new (same "hard
rule" spirit as `lofted_hull._hull_profile_points`'s docstring on silent per-station twist): the
loft/span axis is X (held fixed across one profile, one caller-supplied `x_station`); CHORDWISE
position maps to Y, centered on the chord midpoint (leading edge at y = -chord/2, trailing edge at
y = +chord/2 — NOT leading-edge-at-0, so the profile sits symmetrically about its own local origin
the same way `lofted_spindle`/`lofted_hull` center their width/height half-extents about 0); THICKNESS
maps to Z (the +-yt(x) half-thickness about the zero-camber chord line, since this is a SYMMETRIC
section — no camber-line offset to add). `naca_wing.py` calls this function IDENTICALLY (same n,
same axis mapping) at every span station it lofts — never a per-station deviation — for exactly the
silent-twist-risk reason `lofted_hull.py`'s module docstring documents for its own profile generator.
"""

from __future__ import annotations

import math

_EPS_MM = 1e-9

# NACA 4-digit symmetric thickness-distribution coefficients — CLOSED-TRAILING-EDGE variant (A4
# swapped from the textbook -0.1015 to -0.1036; see module docstring above).
_A0, _A1, _A2, _A3, _A4 = 0.2969, -0.1260, -0.3516, 0.2843, -0.1036


def naca4_half_thickness(x: float, chord: float, thickness_pct: float) -> float:
    """Half-thickness `yt` at chordwise position `x` in `[0, chord]` for a NACA 4-digit SYMMETRIC
    section (e.g. NACA0012 at thickness_pct=12.0). `x=0` is the leading edge, `x=chord` the trailing
    edge. Returns exactly `0.0` at both ends: at `x=0` because every term above has a `sqrt(x/c)` or
    higher power of `x/c` factor (the classic NACA thin-airfoil leading-edge cusp — a real wing's
    physically-rounded LE radius is a higher-order effect this formula doesn't model directly, same
    disclosed-approximation stance `_loft_profiles.py`'s cosine-ease taper already takes relative to
    a real loft), and at `x=chord` by the closed-trailing-edge coefficient choice documented above.
    Clamped to `>= 0.0` defensively (guards float roundoff at the very ends from returning a
    vanishingly small negative)."""
    if chord <= _EPS_MM:
        return 0.0
    t = thickness_pct / 100.0
    xc = max(0.0, min(1.0, x / chord))
    yt = 5.0 * t * chord * (
        _A0 * math.sqrt(xc) + _A1 * xc + _A2 * xc * xc + _A3 * xc ** 3 + _A4 * xc ** 4
    )
    return max(0.0, yt)


def sweep_dihedral_offset(dist_from_center: float, sweep_deg: float, dihedral_deg: float) -> tuple[float, float]:
    """(y_offset, z_offset) from sweep/dihedral for a station `dist_from_center` (>= 0, distance from
    a lofted panel's own centerline toward EITHER end) -- a plain `distance * tan(angle)` shift, so at
    `dist_from_center == 0` both are exactly 0.0 regardless of angle, and both ends (equal
    `dist_from_center`, opposite sign of the raw loft-axis coordinate) get the SAME shift -- the
    physically-correct "both ends sweep aft / rise up relative to the centerline" shape, not a
    one-sided skew. Shared by `naca_wing.py` and `bwb_fuselage.py` -- factored out here (rather than
    each file keeping its own private copy) once a second caller needed the identical math, matching
    this package's own `_loft_profiles.py`/`_cross_sections.py` shared-plumbing precedent."""
    y_offset = dist_from_center * math.tan(math.radians(sweep_deg))
    z_offset = dist_from_center * math.tan(math.radians(dihedral_deg))
    return y_offset, z_offset


def naca4_profile_points(
    x_station: float,
    chord: float,
    thickness_pct: float,
    n_per_side: int = 20,
    y_offset: float = 0.0,
    z_offset: float = 0.0,
) -> list[tuple[float, float, float]]:
    """ONE closed NACA 4-digit symmetric airfoil profile at loft-axis position `x_station`, scaled to
    `chord` at the given `thickness_pct` — see the module docstring's LOCAL AXIS CONVENTION for what
    Y and Z mean here. `y_offset`/`z_offset` shift the whole profile after that mapping — this is how
    `naca_wing.py` applies sweep (a Y shift, proportional to distance from the wing's centerline) and
    dihedral (a Z shift) without the axis convention itself ever changing per station.

    Degenerate `chord <= 0` returns a single point (the caller's cue, matching `lofted_spindle`'s
    `bd.Vertex` substitution convention, to use a true point instead of a zero-area face there).

    Sampled COSINE-spaced (denser near the leading and trailing edges, where curvature/curvature-
    rate is highest — standard airfoil-plotting practice) from the leading edge to the trailing edge
    along the UPPER surface (`n_per_side` points, `yt >= 0`), then back from the trailing edge to the
    leading edge along the LOWER surface (mirrored `y`, `yt <= 0`, same cosine spacing, `n_per_side -
    2` points — the shared leading-edge and trailing-edge points are each visited EXACTLY ONCE, on
    the upper-surface pass, and the loop closes back onto the first point via the periodic spline,
    not a literal duplicate coordinate). Because `yt(0) == yt(chord) == 0.0` exactly (see module
    docstring), the upper and lower surfaces genuinely meet at both ends — a real closed loop, not an
    intentionally-overlapping approximation.
    """
    if chord <= _EPS_MM:
        return [(x_station, y_offset, z_offset)]
    n = max(4, int(n_per_side))
    half_chord = chord / 2.0

    def _xc(i: int) -> float:
        beta = math.pi * i / (n - 1)
        return chord * (1.0 - math.cos(beta)) / 2.0

    pts: list[tuple[float, float, float]] = []
    # Upper surface: leading edge (i=0, xc=0) -> trailing edge (i=n-1, xc=chord).
    for i in range(n):
        xc = _xc(i)
        yt = naca4_half_thickness(xc, chord, thickness_pct)
        pts.append((x_station, xc - half_chord + y_offset, yt + z_offset))
    # Lower surface: trailing edge back to leading edge, EXCLUDING both shared endpoints (already
    # placed above, at yt=0 on both surfaces — see module docstring).
    for i in range(n - 2, 0, -1):
        xc = _xc(i)
        yt = naca4_half_thickness(xc, chord, thickness_pct)
        pts.append((x_station, xc - half_chord + y_offset, -yt + z_offset))
    return pts
