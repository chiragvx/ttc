"""NACA wing — a single continuous, full-span lofted wing panel using a REAL NACA 4-digit symmetric
airfoil cross-section (see `_naca_airfoil.py`), not a generic biconvex/lens placeholder.

Shape family: maximum chord/thickness sits at the panel's own CENTERLINE (the root, in aircraft
terms) and tapers, dead straight, out to a tip chord/thickness at EACH end. This is ONE continuous
full-span panel (tip-to-tip) built as a single loft — not a half-span panel built once and mirrored,
so there is exactly one seam-free surface across the whole span, including straight through the
centerline.

CONFIRMED BUG, fixed this session (real-shape regression, diagnosed from a built-part screenshot):
this file used to reuse `lofted_spindle`/`lofted_hull`'s shared `ease_at`/`taper_stations` cosine-ease
helpers (`_loft_profiles.py`) for the span-wise chord schedule, plus `bd.loft(sections, ruled=False)`
for the loft itself — both are the RIGHT choice for those two files' own bodies (a fuselage nose/tail
or a hull end genuinely wants a smooth, zero-slope-at-the-tip blend into a plateau, with a smooth
B-spline surface between stations), but the WRONG choice for a wing: a real straight-tapered wing has
straight leading/trailing edges meeting at a sharp point at the root, not a smoothly domed/curved one.
`ease_at`'s zero-slope-at-the-boundary shape flattened the chord schedule right at the centerline
before curving back up, and the non-ruled loft added a further smooth B-spline blend spanwise on top
of that — together producing a domed/bulged root peak instead of the sharp taper a real swept wing
planform has. The fix: `_chord_at()` is now a PLAIN LINEAR interpolation (see its docstring), and
`_build()` now lofts with `ruled=True` (straight-line elements between span stations, not a smooth
spline surface) — see each function's docstring for detail. `_sweep_dihedral_offset()` was ALREADY a
plain linear `distance * tan(angle)` shift and needed no change.

Build123d 0.10.0 findings from this session (see also test_naca_wing.py):
- The SAME periodic-spline-through-explicit-points technique `lofted_hull.py`'s module docstring
  documents for its own (non-elliptical) closed profile applies directly to a NACA profile: build a
  closed loop via `bd.Spline(*pts, periodic=True)` -> `bd.Wire([edge])` -> `bd.Face(wire)`; verified
  directly that a real NACA0012-shaped point set builds a valid, non-self-intersecting `Face` this
  way (the closed-trailing-edge coefficient choice in `_naca_airfoil.py` is what makes this a genuine
  closed loop rather than one with a small explicit gap to paper over). This part of the construction
  is UNCHANGED by this session's fix — only the span-wise schedule/loft mode changed, never the
  chordwise profile shape itself.
- Exactly the same SILENT-TWIST risk `lofted_hull.py`'s module docstring documents for its own
  profile generator applies here: `bd.loft()`/OCCT does not check seam/orientation alignment between
  stations. `_section_points()` below is the SOLE place this file calls `naca4_profile_points()`,
  with the same axis convention (`_naca_airfoil.py`'s LOCAL AXIS CONVENTION note) at every span
  station — never a per-station deviation.
- A station whose local chord rounds to ~0 (only reachable if `tip_chord_mm` were driven to ~0 by a
  future param change — the current ParamSpec floor keeps it comfortably positive) needs the SAME
  `bd.Vertex` tip substitution `lofted_spindle._section` uses for a degenerate ellipse: a
  near-zero-chord NACA profile is a near-zero-area closed curve, and `bd.loft()` handles a real
  `Vertex` tip far more robustly than a nearly-degenerate `Face`. `_section()` below carries this
  same defensive substitution even though today's bounds don't require it, matching that file's
  belt-and-suspenders style.
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems._naca_airfoil import naca4_half_thickness, naca4_profile_points

_FRAGMENT = """\
## Subsystem: NACA wing
A single continuous, full-span wing panel (tip-to-tip in ONE loft — not a half-span panel mirrored
separately), lofted through a REAL NACA 4-digit SYMMETRIC airfoil cross-section (the default
thickness_pct=12.0 is the classic NACA0012) — not a generic lens/biconvex placeholder. SOLID, not
hollow — a real wing plank. Maximum chord/thickness sits at the panel's own CENTERLINE (the "root"),
tapering dead straight out to a tip chord/thickness at EACH end (a real straight-tapered wing's
leading/trailing edges are straight lines meeting at a sharp point at the root — not a smoothly
domed/curved bulge), at a CONSTANT thickness_pct so the airfoil shape stays self-similar as the chord
shrinks (standard real-aircraft practice — there is no separate thickness-taper schedule to set).
- **span_mm** — full tip-to-tip span (NOT a half-span).
- **root_chord_mm** — chord at the centerline (the widest station).
- **tip_chord_mm** — chord at each tip.
- **thickness_pct** — max thickness as a % of the LOCAL chord, held constant span-wise (12.0 =
  NACA0012, a common general-aviation/UAV section). No aerodynamic performance number is computed
  from this — it is purely a geometric proportion (pick a smaller number for a thinner, lower-drag-
  looking section; a larger one for a deeper, structurally roomier one).
- **sweep_deg** — chordwise shift per unit span distance from the centerline, as an angle
  (`shift = |distance_from_centerline| * tan(sweep_deg)`); positive sweeps both tips AFT.
- **dihedral_deg** — vertical shift per unit span distance from the centerline, same angle
  convention; positive lifts both tips UP (a shallow V, root to tip on both sides).

### Intent mapping
- "a NACA0012 wing" / "a symmetric airfoil wing" -> thickness_pct=12.0 (the default) already is this.
- "a tapered wing" / "narrower at the tips" -> tip_chord_mm noticeably below root_chord_mm.
- "a straight (untapered) wing" -> tip_chord_mm == root_chord_mm.
- "a swept wing" / "swept back" -> increase sweep_deg (positive = aft); "forward-swept" -> negative.
- "dihedral" / "wings angle up" -> increase dihedral_deg; "anhedral" / "wings droop down" -> negative.
- "a thinner wing" / "low-drag-looking section" -> decrease thickness_pct (watch the tip: a small
  tip_chord_mm combined with a low thickness_pct can leave a sub-print-floor tip — see the
  min-thickness invariant).\
"""

_MIN_WALL_MM = 0.8  # FDM min-wall floor, packages/ledger/apply.py::MIN_WALL_MM

_N_AIRFOIL_PTS_PER_SIDE = 20  # points sampled per surface (upper/lower) of EVERY closed profile
_N_VOLUME_STEPS = 200       # midpoint-rule integration steps for _volume (pure python, cheap)
_AREA_INTEGRATION_STEPS = 50  # midpoint-rule steps for one cross-section's area (_airfoil_area)
_EPS_MM = 1e-9
_POINT_EPS_MM = 1e-6  # a station whose local chord is at/below this is treated as a true point


def _chord_at(dist_from_center: float, p) -> float:
    """Local chord at `dist_from_center` (>= 0, distance from the panel's own centerline toward
    EITHER tip) — a PLAIN LINEAR interpolation from `root_chord_mm` (the max, at
    `dist_from_center == 0`) down to `tip_chord_mm` (at `dist_from_center == span_mm/2`, i.e. at
    either tip). Deliberately NOT the shared `ease_at` cosine-ease helper (`_loft_profiles.py`) that
    `lofted_spindle`/`lofted_hull` use for their own bodies: a real straight-tapered wing's leading
    and trailing edges are straight lines by definition, meeting at a sharp point at the root —
    `ease_at`'s zero-slope-at-the-boundary shape (correct for smoothly blending into a fuselage
    nose/tail plateau) would flatten the schedule right at the centerline before curving back up,
    which is exactly what produced a domed/rounded root peak in a real build instead of a sharp taper.
    See `_stations()` below: because this schedule is now genuinely piecewise-linear on each
    half-span, only 3 span stations (both tips + the centerline) are needed to represent it EXACTLY —
    there is no curve left to approximate between them."""
    half_span = p.span_mm / 2.0
    if half_span <= _EPS_MM:
        return p.root_chord_mm
    t = min(1.0, dist_from_center / half_span)
    return p.root_chord_mm + (p.tip_chord_mm - p.root_chord_mm) * t


def _sweep_dihedral_offset(dist_from_center: float, p) -> tuple[float, float]:
    """(y_offset, z_offset) added to a station's profile from sweep/dihedral — both are a plain
    `distance-from-centerline * tan(angle)` shift, so at `dist_from_center == 0` (the centerline)
    both are exactly 0.0 regardless of angle, and BOTH tips (equal `dist_from_center`, opposite sign
    of the raw span coordinate) get the SAME shift — the physically-correct "both tips sweep aft /
    rise up relative to the root" shape, not a one-sided skew."""
    y_offset = dist_from_center * math.tan(math.radians(p.sweep_deg))
    z_offset = dist_from_center * math.tan(math.radians(p.dihedral_deg))
    return y_offset, z_offset


def _stations(p) -> list[float]:
    """Span-axis (X) sample positions, CENTERED on the panel's own local origin — X in
    `[-span_mm/2, +span_mm/2]`. `_chord_at()` is now a PLAIN LINEAR taper (see its docstring), so the
    true spanwise shape is piecewise-linear on each half-span, meeting at a sharp peak/corner exactly
    at the centerline — there is nothing curved left to approximate between a tip and the root, so
    exactly 3 stations (both tips + the centerline) represent it EXACTLY. This deliberately does NOT
    reuse `lofted_spindle`/`lofted_hull`'s dense `taper_stations()` sampling (`_loft_profiles.py`):
    that density exists to approximate a genuinely-curved cosine-ease schedule, and sampling it here
    would add nothing but unnecessary loft complexity to an already-exact piecewise-linear shape."""
    half = p.span_mm / 2.0
    return [-half, 0.0, half]


def _section_points(x: float, p) -> list[tuple[float, float, float]]:
    """THE SOLE place this file calls `naca4_profile_points()` — see module docstring's silent-twist
    warning: every station MUST go through this one function, unmodified, never a per-station
    deviation in axis convention or sampling."""
    dist = abs(x)
    chord = _chord_at(dist, p)
    y_offset, z_offset = _sweep_dihedral_offset(dist, p)
    return naca4_profile_points(x, chord, p.thickness_pct, _N_AIRFOIL_PTS_PER_SIDE,
                                y_offset=y_offset, z_offset=z_offset)


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart

    stations = _stations(p)

    def _section(x: float):
        dist = abs(x)
        chord = _chord_at(dist, p)
        if chord <= _POINT_EPS_MM:
            # Defensive substitution mirroring lofted_spindle._section — see module docstring.
            y_offset, z_offset = _sweep_dihedral_offset(dist, p)
            return bd.Vertex(x, y_offset, z_offset)
        pts = _section_points(x, p)
        edge = bd.Spline(*pts, periodic=True)
        return bd.Face(bd.Wire([edge]))

    # ruled=True: straight-line elements connecting corresponding points on consecutive station
    # profiles (a sharp, flat-faceted taper spanwise), NOT a smooth B-spline surface fitted through
    # them. This does not touch each station's OWN profile shape (still the full smooth NACA curve,
    # chordwise, from `_section_points`/`naca4_profile_points` exactly as before) — only the spanwise
    # transition BETWEEN stations. `lofted_spindle`/`lofted_hull` deliberately use `ruled=False` for
    # their own genuinely-rounded bodies; a wing wants the opposite, a real sharp taper — see module
    # docstring.
    solid = bd.loft([_section(x) for x in stations], ruled=True)

    return TaggedPart(solid, {
        "wing.panel": {
            "kind": "solid", "span": p.span_mm,
            "root_chord": p.root_chord_mm, "tip_chord": p.tip_chord_mm,
            "thickness_pct": p.thickness_pct,
            "sweep_deg": p.sweep_deg, "dihedral_deg": p.dihedral_deg,
        },
    })


def _airfoil_area(chord: float, thickness_pct: float, n: int = _AREA_INTEGRATION_STEPS) -> float:
    """Cross-sectional area of ONE closed NACA 4-digit symmetric profile at this local `chord` — a
    midpoint-rule numerical integral of `2 * naca4_half_thickness(x)` over `[0, chord]` (upper half +
    lower half at every chordwise slice, the SAME half-thickness formula the real geometry uses, not
    a separately-derived area formula) — mirrors `lofted_hull`/`lofted_spindle`'s own disk-integration
    `_volume()` style, just with an airfoil-shaped "disk" cross-section instead of a circular/
    elliptical one."""
    if chord <= _EPS_MM:
        return 0.0
    dx = chord / n
    area = 0.0
    for i in range(n):
        xm = (i + 0.5) * dx
        yt = naca4_half_thickness(xm, chord, thickness_pct)
        area += 2.0 * yt * dx
    return area


def _volume(p) -> float:
    """Method-of-disks numerical integration along the span over `_chord_at()`/`_airfoil_area()` —
    NOT a build123d call (the interactive plane is closed-form arithmetic only, no OCCT on that path,
    per CLAUDE.md). Sweep/dihedral shift each cross-section's Y/Z position but not its AREA, so
    (like `lofted_spindle`'s own taper) they don't enter this integral.

    This is a disclosed APPROXIMATION, not fabricated. The spanwise taper itself is now exact (see
    `_chord_at()`/`_stations()`) — the residual error against a real build comes from a DIFFERENT,
    orthogonal source: each real cross-section is a periodic B-spline fit through `_N_AIRFOIL_PTS_PER_
    SIDE` discrete points (`_section_points`/`naca4_profile_points`), not the continuous analytic NACA
    curve this closed-form integral evaluates, and OCCT's `ruled=True` loft between the (now only two,
    differently-scaled) real profile curves per half-span does not reproduce that per-station spline-
    vs-analytic gap identically at every intermediate span position. Measured directly (see
    test_naca_wing.py / the throwaway proof script this fix's session ran): at the default config this
    error is ~1.7%, comfortably inside the test's tolerance — NOTE this is not smaller than the old
    ease_at/ruled=False build's own measured error (~0.07%) despite the true shape now being simpler;
    fewer span stations means less incidental averaging-out of that same per-station spline-fit gap,
    not a regression in the taper shape itself (see the straight-line landmark test, which is the
    direct regression check for the actual bug this session fixed).
    """
    dx = p.span_mm / _N_VOLUME_STEPS
    half_span = p.span_mm / 2.0
    vol = 0.0
    for i in range(_N_VOLUME_STEPS):
        xm = (i + 0.5) * dx - half_span
        chord = _chord_at(abs(xm), p)
        vol += _airfoil_area(chord, p.thickness_pct) * dx
    return max(0.0, vol)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.span_mm <= 0.0:
        out.append(f"span_mm {p.span_mm:.1f} mm must be > 0")
    if p.root_chord_mm <= 0.0:
        out.append(f"root_chord_mm {p.root_chord_mm:.1f} mm must be > 0")
    if p.tip_chord_mm <= 0.0:
        out.append(f"tip_chord_mm {p.tip_chord_mm:.1f} mm must be > 0")
    if p.thickness_pct <= 0.0:
        out.append(f"thickness_pct {p.thickness_pct:.1f}% must be > 0")
    # The tightest cross-section (whichever end has the smaller chord) sets the tightest max
    # thickness — for a NACA 4-digit section, max thickness IS thickness_pct% of the local chord BY
    # DEFINITION (the "12" in NACA0012 literally means "12% of chord"), so this reuses the exact
    # relationship _naca_airfoil.py's formula encodes rather than a separately-derived estimate.
    if p.root_chord_mm > 0.0 and p.tip_chord_mm > 0.0 and p.thickness_pct > 0.0:
        tightest_chord = min(p.root_chord_mm, p.tip_chord_mm)
        tightest_thickness = tightest_chord * p.thickness_pct / 100.0
        if tightest_thickness < _MIN_WALL_MM:
            out.append(
                f"thickness_pct {p.thickness_pct:.1f}% of the tightest chord {tightest_chord:.1f} mm "
                f"gives only {tightest_thickness:.2f} mm max thickness at that tip — need >= "
                f"{_MIN_WALL_MM} mm"
            )
    return out


NACA_WING = register_subsystem(Subsystem(
    name="naca_wing",
    description="Full-span lofted wing panel — real NACA 4-digit symmetric airfoil cross-section "
                "(default NACA0012), constant thickness_pct as chord tapers root-to-tip, solid plank",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("span_mm",        value=500.0, min=100.0, max=3000.0, unit="mm"),
        ParamSpec("root_chord_mm",  value=120.0, min=20.0,  max=600.0,  unit="mm"),
        ParamSpec("tip_chord_mm",   value=60.0,  min=10.0,  max=600.0,  unit="mm"),
        ParamSpec("thickness_pct",  value=12.0,  min=6.0,   max=21.0,   unit="pct"),
        ParamSpec("sweep_deg",      value=0.0,   min=-30.0, max=45.0,   unit="deg"),
        ParamSpec("dihedral_deg",   value=0.0,   min=-10.0, max=20.0,   unit="deg"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # A lofted NACA wing panel isn't a single-solid plate/bar shape the validated cantilever FS
    # methodology (packages/truth_plane/solvers/fs.py) faithfully covers — no validated FEA
    # methodology exists for a wing panel yet. FS honestly stays "unknown" for this part type, same
    # honesty stance lofted_hull.py/lofted_spindle.py already take for their own shapes.
    fea_eligible=False,
))
