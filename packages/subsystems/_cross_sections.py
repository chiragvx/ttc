"""Shared build123d cross-section builders for multi-station lofted bodies (`tube_fuselage`, and any
future named-station loft such as a blended-wing-body fuselage that reuses this same "named stations,
each independently shaped" plumbing). Split out of `_loft_profiles.py` (pure python, no OCCT) because
this file imports build123d directly -- only ever reached from inside a subsystem's `_build()`, same
gating as `packages/truth_plane/regen/templated.py`'s own top-level `import build123d as bd`.

Verified directly in build123d 0.10.0 this session:
- `bd.Ellipse(h_half, w_half)` intersected with a `bd.Rectangle` positioned to cover only the region
  above a flat cutoff line produces a valid face whose bounding box and area match the closed-form
  `_loft_profiles.ellipse_segment_kept_area` formula exactly (both the `keel_flat_mm=0`, i.e. plain
  ellipse, case and a real flattened case were checked directly against the built face's own
  `.area`) -- a robust way to get a "not a perfect ellipse" cross-section (a real fuselage's
  flattened cargo-floor keel line) without authoring arbitrary vertices, so every station stays a
  handful of named scalars (typed ledger deltas), never free-form geometry.
- Mixing this keeled face with a plain `bd.Vertex` tip (for a station that tapers to a true point) in
  the SAME `bd.loft()` call works exactly like `lofted_spindle.py`/`ogive_fuselage.py`'s existing
  Vertex-tip substitution.
- A HOLLOW shell built the outer-loft-minus-inner-loft way (same technique `lofted_spindle.py` uses)
  is numerically fragile here: sweeping the station count from 6 to 30 on a keeled, large-diameter,
  thin-wall tube produced wildly unstable results (13.6% error at 10 stations, but `nsolids=2` at 12,
  `is_valid=False` at 16, 40%+ error at 20, `is_valid=False` again at 30) -- the same "loft
  instability, not genuine convergence" finding `lofted_spindle.py`/`ogive_fuselage.py`'s own module
  docstrings already report for THEIR simpler (non-keeled) lofts, just worse here because the keel
  cut adds a second source of per-station topological change. A SOLID body (no hollow subtraction) at
  the same keeled proportions was stable across the entire 6-16 station sweep (~20.5-20.7% error,
  `is_valid=True`, one solid, every time) -- solid is what `tube_fuselage.py` builds for exactly this
  reason, following the same solid-for-now precedent `ogive_fuselage.py`/`winged_fuselage.py` already
  established ("we can use shell command on a fuselage later").
"""

from __future__ import annotations

import build123d as bd

_POINT_EPS_MM = 1e-6


def keeled_ellipse_face(h_half: float, w_half: float, keel_flat_mm: float):
    """An ellipse (`h_half` along the local axis that `station_face`'s `Rotation(0, 90, 0)` maps
    onto global Z / height, `w_half` onto global Y / width) with its bottom flattened by
    `keel_flat_mm` -- built by intersecting the full ellipse with a rectangle covering everything
    below the flattened line, so the result is always a real OCCT face/wire, never hand-authored
    vertices. `keel_flat_mm <= 0` returns a plain `bd.Ellipse` (no intersection op at all).

    `Rotation(0, 90, 0)` maps LOCAL +X to GLOBAL -Z (verified directly: `Rotation(0,90,0) *
    Pos(10,0,0) * Vertex(0,0,0)` lands at global `(0, 0, -10)`, not `+10`) -- so flattening the
    GLOBAL bottom (removing the most-negative Z) means keeping the region where local X is LARGE
    (near `+h_half`), i.e. clipping away local X BELOW `h_half - keel_flat_mm`, the opposite sign
    from what the naive "local X near -h_half is the bottom" assumption would suggest."""
    ell = bd.Ellipse(h_half, w_half)
    if keel_flat_mm <= _POINT_EPS_MM:
        return ell
    cutoff = h_half - keel_flat_mm  # KEEP local X <= cutoff (maps to global Z >= -cutoff, the belly)
    # A generously oversized rectangle (independent of any one caller's own scale) so the intersection
    # never itself becomes the limiting boundary -- only `cutoff` should ever clip the ellipse.
    big = 4.0 * (h_half + w_half + keel_flat_mm) + 10.0
    rect = bd.Pos(cutoff - big / 2.0, 0) * bd.Rectangle(big, big)
    return ell & rect


def station_face(x: float, w_half: float, h_half: float, keel_flat_mm: float):
    """One placed loft section at axial position `x`: a `bd.Vertex` tip whenever EITHER half-extent
    collapses to ~0 (same rule `lofted_spindle.py`/`ogive_fuselage.py` use for a true pointed tip),
    otherwise a `keeled_ellipse_face` rotated so local h_half/w_half map onto global Z/Y and placed at
    `x` along the loft axis -- the identical `Rotation(0, 90, 0)` convention already verified in
    `lofted_spindle.py`'s own module docstring."""
    if w_half <= _POINT_EPS_MM or h_half <= _POINT_EPS_MM:
        return bd.Vertex(x, 0, 0)
    face = keeled_ellipse_face(h_half, w_half, keel_flat_mm)
    return bd.Pos(x, 0, 0) * (bd.Rotation(0, 90, 0) * face)
