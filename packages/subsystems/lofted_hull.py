"""Lofted hull — an ASYMMETRIC top/bottom body of revolution + a localized canopy bump.

`lofted_spindle.py` lofts circular/elliptical cross-sections: top and bottom are always mirror
images of each other. A real fuselage (or a boat hull, a car body) is not — it has a flatter
underside and a rounder/bulged top (a canopy, a cabin), and often a LOCALIZED bulge (a canopy) that
does not run the full length. This subsystem is the asymmetric sibling: independent height-above-
centerline vs. height-below-centerline at the widest station, plus an optional canopy-bump zone that
adds extra height to the TOP only, faded in and out (never an abrupt step).

Shares the cosine-ease taper/station-sampling math with `lofted_spindle.py` via
`packages/subsystems/_loft_profiles.py` (extracted this session — see that file and the Part A diff
to `lofted_spindle.py`), rather than duplicating the taper formula a third time.

Build123d 0.10.0 findings from THIS session (asymmetric-profile-specific; see also
`lofted_spindle.py`'s module docstring for the shared loft/offset findings both files rely on, and
`test_lofted_hull.py`):
- A genuinely asymmetric (top != bottom) closed profile builds cleanly via a periodic Spline through
  explicit points: `bd.Spline(*pts, periodic=True)` produces a closed `Edge` (`edge.is_closed ->
  True`), `bd.Wire([edge])` is closed, `bd.Face(wire)` is a valid `Face` — verified directly. This
  "biconvex" construction (`_hull_profile_points` below: height_top above the profile centerline,
  height_bottom below it, at a shared set of angles) is what's used — NOT `Polygon`, NOT a
  circle-union "snowman" trick, NOT any concave-waist construction.
- `bd.offset()` is unreliable on spline-based 2D faces — tested directly at increasing point density
  (n=8,16,24,32,48,64): failures were NON-MONOTONIC (n=24 and n=32 raised `ValueError: Null
  TopoDS_Shape object`; n=48 and n=64 succeeded), and forcing near-symmetry didn't fix it. Combined
  with the ALREADY-DOCUMENTED 3D-solid `bd.offset()` segfault risk (`lofted_spindle.py`'s module
  docstring), `bd.offset()` is not used anywhere in this file, on either the 2D profile or the 3D
  solid — hollowing here uses the SAME inner-loft-and-subtract technique `lofted_spindle._build`
  already ships (a second, shrunk-by-`wall_thickness_mm` loft, boolean-subtracted).
- CONFIRMED SILENT-TWIST RISK: `bd.loft()`/OCCT does NOT check seam/orientation alignment between
  stations — rotating one interior station's profile 30/90/180 degrees relative to its neighbors
  produced a smooth, SILENT corkscrew twist every time, `is_valid` staying `True` throughout (traced
  to bare `BRepOffsetAPI_ThruSections` with no seam hint). `_hull_profile_points` below is the SOLE
  place this file defines what "top" means, called IDENTICALLY (same angle sampling, same starting
  angle, same direction) at every station — see that function's docstring for the hard rule.
  `is_valid == True` is explicitly NOT sufficient evidence of a correct loft — see
  `test_lofted_hull.py`'s cross-section landmark-angle test, which asserts this directly rather than
  trusting `is_valid` alone.
- A SECOND, NEWLY-DISCOVERED risk this session, orthogonal to the silent-twist one above: with only
  the taper-zone + bump-zone stations (mirroring `lofted_spindle`'s sparse "flat plateau needs no
  interior stations" assumption), a WIDE gap between real stations (e.g. the 60mm gap between the
  start-taper zone ending and the canopy-bump zone beginning, on a 300mm-long hull) let the outer loft
  and the (independently-lofted) cavity loft bulge by DIFFERENT amounts inside that gap — even though
  both stations bounding the gap were geometrically IDENTICAL on each loft. The result: the cavity
  surface poked slightly OUTSIDE the outer surface partway through the gap, so the boolean subtract
  produced a locally broken/asymmetric shell there (reproduced directly: cross-section slice at the
  midpoint of the gap showed the "top" landmark 29mm off-center, `is_valid` still reporting `True` on
  one repro and `False` on a second, more extreme one — an unreliable, inconsistent signal either
  way). Unlike `lofted_spindle`, this profile is a spline through discrete points, not an analytic
  conic, and evidently doesn't tolerate the same sparse "plateau needs no interior stations" shortcut.
  The fix: `_stations()` below ALSO samples a fixed-count "backbone" of stations evenly across the
  ENTIRE length (`_N_BACKBONE_STATIONS`), independent of the taper/bump zones, closing any wide gap.
  Verified directly at backbone counts down to 10 (a 300mm hull) and 16 (a 1200mm hull) — both fixed
  the reproduced defect; `_N_BACKBONE_STATIONS = 16` is used below for headroom over that.
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems._loft_profiles import ease_at, taper_stations, zone_samples

_FRAGMENT = """\
## Subsystem: Lofted hull
A smooth loft between ASYMMETRIC (top != bottom) cross-sections along one axis, hollowed to a
constant-wall shell — the shape family behind a real fuselage/canopy, a boat hull, a car body: a
flatter underside, a rounder/bulged top, optionally with a LOCALIZED canopy bulge that doesn't run the
whole length. This is `lofted_spindle`'s asymmetric sibling — reach for `lofted_hull` specifically
when "flattened belly", "canopy bulge", or "not rotationally symmetric top-to-bottom" was actually
described; reach for the simpler `lofted_spindle` (with max_width_mm/max_height_mm, still
rotationally-symmetric top-to-bottom) otherwise.
- **length_mm** — overall length along the axis.
- **max_width_mm** — cross-section width at the widest point (the plateau between the two tapers).
- **start_taper_mm / end_taper_mm** — length of the tapering region at each end (same role as
  `lofted_spindle`: the widest point sits wherever start_taper_mm ends).
- **start_width_mm / end_width_mm** — tip width at each end. 0/0 tapers all the way to a true point.
- **max_height_top_mm / max_height_bottom_mm** — independent above/below-centerline sizing AT THE
  WIDEST STATION — this is what makes the cross-section asymmetric (a canopy-like top, a flatter
  bottom, or vice versa). Both taper toward 0 in lockstep with the width schedule at each tip (a
  pointed/blunt nose or tail closes in every direction together, never leaves a knife-edge).
- **bump_start_pct / bump_length_pct** — where (0-100% of length_mm) a LOCALIZED canopy bump zone
  starts and how much of the length it spans. Must satisfy bump_start_pct + bump_length_pct <= 100.
- **bump_height_mm** — extra height ABOVE the base top profile at the bump's peak, faded in/out
  smoothly across the zone (never an abrupt step). 0 = no bump (a plain asymmetric hull).
- **wall_thickness_mm** — hollow shell wall thickness.

### Intent mapping
- "a fuselage with a canopy" / "flatter belly, rounded cabin on top" -> max_height_top_mm noticeably
  above max_height_bottom_mm, plus a nonzero bump_height_mm positioned (bump_start_pct) roughly where
  the cockpit/cabin sits.
- "not rotationally symmetric" / "flatter underside" -> max_height_bottom_mm below max_height_top_mm
  (or vice versa for a keel-like shape) even with bump_height_mm=0.
- "a rounded canopy over the cockpit, about a third of the way back" -> bump_start_pct ~= 25-35,
  bump_length_pct sized to the canopy's real length as a % of the hull, bump_height_mm to taste.
- "pointed nose" / "pointed tail" -> start_width_mm=0 (or end_width_mm=0); height tapers to the same
  point automatically, no separate height tip params needed.
- "thicker wall" / "heavier" -> increase **wall_thickness_mm** (watch the tips: the tightest of
  width/height_top/height_bottom must keep at least the 0.8 mm min-wall floor once hollowed).\
"""

_MIN_WALL_MM = 0.8  # FDM min-wall floor, packages/ledger/apply.py::MIN_WALL_MM

_N_TAPER_STATIONS = 8     # stations sampled per taper zone — matches lofted_spindle's density
_N_BUMP_STATIONS = 8      # stations sampled across the canopy-bump zone (rise + peak + fall)
_N_BACKBONE_STATIONS = 16 # whole-length safety-net stations — see module docstring's 2nd risk finding
_N_PROFILE_PTS = 28       # points sampled around EVERY closed profile — see _hull_profile_points
_N_VOLUME_STEPS = 200     # midpoint-rule disk-integration steps for _volume (pure python, cheap)
_EPS_MM = 1e-9
_POINT_EPS_MM = 1e-6  # a station whose width half-extent is at/below this is treated as a true point


def _bump_amount(x: float, p) -> float:
    """Extra height ABOVE the base height_top profile from the canopy-bump zone at axial position x
    — a single smooth hump (0 at both edges of the zone and everywhere outside it, `bump_height_mm`
    at the zone's exact midpoint), faded in/out via the SAME `ease_at` cosine-ease helper the axial
    taper uses (packages/subsystems/_loft_profiles.py) — never an abrupt step. Reuses `ease_at` by
    treating the bump zone as its own mini "rise-then-fall" taper with a zero-width plateau at its
    center (x_a == x_b == half the zone's length)."""
    bump_start = p.length_mm * p.bump_start_pct / 100.0
    bump_end = bump_start + p.length_mm * p.bump_length_pct / 100.0
    if bump_end - bump_start <= _EPS_MM or x <= bump_start or x >= bump_end:
        return 0.0
    local_len = bump_end - bump_start
    local_mid = local_len / 2.0
    return ease_at(x - bump_start, local_mid, local_mid, local_len, 0.0, p.bump_height_mm, 0.0)


def _station_dims(x: float, p) -> tuple[float, float, float]:
    """(width_half, height_top_half, height_bottom_half) at axial position x — width follows the
    shared cosine-ease taper (start_width_mm -> max_width_mm -> end_width_mm, same as
    lofted_spindle's radius schedule); height_top/height_bottom are DERIVED as width's taper
    FRACTION times their own max value, so all three dimensions collapse to a true point together at
    a pointed tip (never one dimension reaching zero while another stays open — see module
    docstring's silent-twist-adjacent risks and `lofted_spindle`'s own degenerate-ellipse finding).
    The canopy bump is added to height_top ONLY, and ONLY where the base cross-section is real
    (width_half above the point epsilon) — layering it onto an already-collapsing tip would leave
    height_top nonzero while width/height_bottom are ~0, a degenerate "folded" profile; the bump
    zone is meant to size a localized MID-body canopy, not to reach a pointed nose/tail anyway, so
    this clamp only ever engages in a practically-zero-width band right at a true point tip."""
    x_a = p.start_taper_mm
    x_b = p.length_mm - p.end_taper_mm
    width_half = ease_at(x, x_a, x_b, p.length_mm,
                        p.start_width_mm / 2.0, p.max_width_mm / 2.0, p.end_width_mm / 2.0)
    max_width_half = p.max_width_mm / 2.0
    scale = width_half / max_width_half if max_width_half > _EPS_MM else 0.0
    height_top_half = (p.max_height_top_mm / 2.0) * scale
    height_bottom_half = (p.max_height_bottom_mm / 2.0) * scale
    if width_half > _POINT_EPS_MM:
        height_top_half += _bump_amount(x, p)
    return width_half, height_top_half, height_bottom_half


def _hull_profile_points(x: float, width_half: float, height_top_half: float, height_bottom_half: float,
                          n: int = _N_PROFILE_PTS) -> list[tuple[float, float, float]]:
    """THE SOLE place this subsystem defines what "top" means for a station's closed asymmetric
    profile: n points swept at angles theta = 2*pi*i/n for i in [0, n), ALWAYS starting at theta=0
    and ALWAYS sweeping the same direction — a "biconvex" double-radius closed curve (the
    sin(theta) >= 0 half uses height_top_half, the sin(theta) < 0 half uses height_bottom_half; NOT
    an ellipse, NOT a Polygon, NOT a circle-union trick).

    HARD RULE (do not violate — see module docstring's confirmed silent-twist finding): every single
    station along the hull MUST call this exact function, with this exact angle sampling, in this
    exact reference frame — NEVER introduce a per-station rotation or a varying starting angle here.
    bd.loft()/OCCT does not check seam/orientation alignment between stations; the only thing
    preventing a smooth, silent corkscrew twist (which still reports is_valid=True) is every station
    sharing this one generator, unmodified.
    """
    pts = []
    for i in range(n):
        theta = 2.0 * math.pi * i / n
        y = width_half * math.cos(theta)
        h = height_top_half if math.sin(theta) >= 0.0 else height_bottom_half
        z = h * math.sin(theta)
        pts.append((x, y, z))
    return pts


def _bump_stations(p) -> list[float]:
    """Extra axial samples spanning the canopy-bump zone (rise, peak, fall) — without these, a bump
    entirely inside the width-taper's flat plateau (the common case) would sit between only the two
    plateau-boundary stations and never appear in the loft at all."""
    bump_start = p.length_mm * p.bump_start_pct / 100.0
    bump_len = p.length_mm * p.bump_length_pct / 100.0
    if bump_len <= _EPS_MM or p.bump_height_mm <= _EPS_MM:
        return []
    return zone_samples(bump_start, bump_start + bump_len, _N_BUMP_STATIONS)


def _stations(p) -> list[tuple[float, float, float, float]]:
    """(x, width_half, height_top_half, height_bottom_half) quadruples for _build()'s outer loft:
    the shared taper-zone stations, the canopy-bump-zone stations, AND a fixed-count whole-length
    "backbone" (see module docstring's 2nd finding — a spline-profile loft needs this even across a
    nominally-unchanging plateau, unlike lofted_spindle's analytic-circle loft). Deduplicated where
    two samples land within _EPS_MM of each other. Pure python (no build123d) so _volume() reuses the
    exact same schedule."""
    xs = sorted(
        set(taper_stations(p.length_mm, p.start_taper_mm, p.end_taper_mm, _N_TAPER_STATIONS))
        | set(_bump_stations(p))
        | set(zone_samples(0.0, p.length_mm, _N_BACKBONE_STATIONS))
    )
    deduped: list[float] = []
    for x in xs:
        if not deduped or x - deduped[-1] > _EPS_MM:
            deduped.append(x)
    return [(x,) + _station_dims(x, p) for x in deduped]


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart

    stations = _stations(p)

    def _section(x: float, w: float, ht: float, hb: float):
        # width_half alone is the "has this station collapsed to a true point" signal: height_top/
        # height_bottom are DERIVED as a proportional scale of width (see _station_dims), so they
        # always collapse in lockstep with it — checking width alone avoids a fragile three-way
        # epsilon comparison against three independently-rounded floats.
        if w <= _POINT_EPS_MM:
            return bd.Vertex(x, 0, 0)
        pts = _hull_profile_points(x, w, ht, hb)
        edge = bd.Spline(*pts, periodic=True)
        return bd.Face(bd.Wire([edge]))

    outer = bd.loft([_section(x, w, ht, hb) for x, w, ht, hb in stations], ruled=False)

    # Hollow via an INNER loft + boolean subtract, NOT bd.offset() on either the 2D profile or the
    # 3D solid — see module docstring. Stations where wall_thickness_mm would eat through ANY of the
    # three dimensions (not just one) are dropped, mirroring lofted_spindle._build exactly: a wall of
    # nonzero thickness cannot reach a zero-thickness point anyway, so the cavity loft caps itself
    # short of the tip with a small flat disc instead.
    inner_stations = []
    for x, w, ht, hb in stations:
        iw, iht, ihb = w - p.wall_thickness_mm, ht - p.wall_thickness_mm, hb - p.wall_thickness_mm
        if iw > _POINT_EPS_MM and iht > _POINT_EPS_MM and ihb > _POINT_EPS_MM:
            inner_stations.append((x, iw, iht, ihb))

    hollowed = False
    if len(inner_stations) >= 2:
        cavity = bd.loft([_section(x, w, ht, hb) for x, w, ht, hb in inner_stations], ruled=False)
        solid = outer - cavity
        hollowed = True
    else:
        # too thin everywhere (relative to wall_thickness_mm) for any cavity to fit — stays solid
        # rather than risk a degenerate cavity loft. _check()'s min-wall invariant is what should
        # catch this upstream; this is a defensive fallback, not the expected path.
        solid = outer

    # CONFIRMED REAL RISK (found this session, see module docstring): for a sufficiently pronounced
    # canopy bump — a LOCALIZED excursion in one dimension surrounded by much flatter neighboring
    # stations — bd.loft()'s ThruSections algorithm can produce a self-intersecting/mis-oriented
    # cavity surface that still reports is_valid=True, silently subtracting far LESS material than
    # intended (measured: a real subtracted volume ~4x the closed-form target in one reproduction).
    # Verified directly this session that this is NOT a station-density artifact (persisted up to
    # 188 stations) and NOT a fixed aspect-ratio/geometry-ratio threshold (the same ratio broke at
    # one absolute scale and not another — an OCCT numerical-tolerance interaction, not a describable
    # design constraint safe to invariant-gate with a formula). No amount of parameter tuning found a
    # reliable general fix; this needs real OCCT engineering attention (see CLAUDE.md's "where Claude
    # needs a human wall" — OCP FFI numerical behavior is explicitly out of scope for self-certifying
    # here). Until then: compare the real build against the closed-form _volume() estimate (the two
    # normally agree to within the same "few percent to ~15%" bulge documented in lofted_spindle.py);
    # a MUCH larger divergence than that is the confirmed signature of this defect, and there is no
    # safe way to "fix" a mis-oriented boolean result after the fact — fall back to the (verified-
    # solid, verified-volume-accurate in every reproduction) unhollowed outer loft instead of shipping
    # a part that LOOKS hollow but silently isn't, rather than raise and block a design outright.
    if hollowed:
        approx_shell_vol = _volume(p)
        if approx_shell_vol > _EPS_MM and abs(solid.volume - approx_shell_vol) / approx_shell_vol > 0.4:
            solid = outer
            hollowed = False

    return TaggedPart(solid, {
        "hull.body": {
            "kind": "solid", "length": p.length_mm, "max_width": p.max_width_mm,
            "max_height_top": p.max_height_top_mm, "max_height_bottom": p.max_height_bottom_mm,
            "bump_height": p.bump_height_mm, "hollowed": hollowed,
        },
    })


def _volume(p) -> float:
    """Method-of-disks numerical integration over _station_dims() — NOT a build123d call (the
    interactive plane is closed-form arithmetic only, no OCCT on that path, per CLAUDE.md). Each
    disk's area is the exact closed-form area of the idealized biconvex profile (upper half-ellipse
    of semi-axes width_half/height_top_half UNION lower half-ellipse of semi-axes
    width_half/height_bottom_half): `area = (pi/2) * width_half * (height_top_half + height_bottom_half)`
    — reduces to a plain ellipse's `pi * width_half * height_half` exactly when height_top_half ==
    height_bottom_half. Outer volume minus an inner integral at each half-extent reduced by
    wall_thickness_mm (clamped to 0 wherever that would go negative), matching _build()'s inner-loft
    station filtering.

    This is a disclosed APPROXIMATION, not fabricated: the real loft is a smooth surface through
    discrete spline profiles, not a literal sweep of this closed-form area, so the true solid departs
    from it somewhat between stations (bulge or undershoot). See test_lofted_hull.py's tolerance
    check (run at the default config) for the measured error.
    """
    dx = p.length_mm / _N_VOLUME_STEPS
    outer_vol = 0.0
    inner_vol = 0.0
    for i in range(_N_VOLUME_STEPS):
        xm = (i + 0.5) * dx
        w, ht, hb = _station_dims(xm, p)
        outer_vol += (math.pi / 2.0) * w * (ht + hb) * dx
        wi = max(0.0, w - p.wall_thickness_mm)
        hti = max(0.0, ht - p.wall_thickness_mm)
        hbi = max(0.0, hb - p.wall_thickness_mm)
        inner_vol += (math.pi / 2.0) * wi * (hti + hbi) * dx
    return max(0.0, outer_vol - inner_vol)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.start_taper_mm + p.end_taper_mm > p.length_mm:
        out.append(
            f"start_taper {p.start_taper_mm:.1f} mm + end_taper {p.end_taper_mm:.1f} mm exceeds "
            f"length {p.length_mm:.1f} mm — tapers overlap"
        )
    if not (0.0 <= p.start_width_mm < p.max_width_mm):
        out.append(f"start_width {p.start_width_mm:.1f} mm must be >= 0 and < max_width {p.max_width_mm:.1f} mm")
    if not (0.0 <= p.end_width_mm < p.max_width_mm):
        out.append(f"end_width {p.end_width_mm:.1f} mm must be >= 0 and < max_width {p.max_width_mm:.1f} mm")
    # Tightest across BOTH tip stations and ALL THREE dimensions — reuses the exact _station_dims()
    # the real build uses (rather than a separately-derived formula) so this invariant can never
    # drift from the real geometry. The cosine-ease taper is monotonic within each zone, so the two
    # tip stations (x=0, x=length_mm) are always the global minimum for width/height_top/
    # height_bottom — the bump can only ever ADD height_top away from a tip, never narrow one.
    tightest_half = min(*_station_dims(0.0, p), *_station_dims(p.length_mm, p))
    if tightest_half - p.wall_thickness_mm < _MIN_WALL_MM:
        out.append(
            f"wall_thickness {p.wall_thickness_mm:.2f} mm leaves only "
            f"{tightest_half - p.wall_thickness_mm:.2f} mm of material at the tightest tip "
            f"(half-extent {tightest_half:.2f} mm) — need >= {_MIN_WALL_MM} mm"
        )
    if p.bump_start_pct + p.bump_length_pct > 100.0:
        out.append(
            f"bump_start_pct {p.bump_start_pct:.1f} + bump_length_pct {p.bump_length_pct:.1f} "
            f"exceeds 100 — the canopy bump zone doesn't fit within the body length"
        )
    return out


LOFTED_HULL = register_subsystem(Subsystem(
    name="lofted_hull",
    description="Asymmetric top/bottom body of revolution + optional localized canopy bump — a "
                "real (non-rotationally-symmetric) fuselage/hull shape, hollowed to a constant-wall shell",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",            value=300.0, min=50.0, max=2000.0, unit="mm"),
        ParamSpec("max_width_mm",         value=80.0,  min=15.0, max=500.0,  unit="mm"),
        ParamSpec("start_taper_mm",       value=60.0,  min=0.0,  max=1000.0, unit="mm"),
        ParamSpec("end_taper_mm",         value=100.0, min=0.0,  max=1000.0, unit="mm"),
        ParamSpec("start_width_mm",       value=15.0,  min=0.0,  max=500.0,  unit="mm"),
        ParamSpec("end_width_mm",         value=14.0,  min=0.0,  max=500.0,  unit="mm"),
        ParamSpec("max_height_top_mm",    value=45.0,  min=5.0,  max=300.0,  unit="mm"),
        ParamSpec("max_height_bottom_mm", value=35.0,  min=5.0,  max=300.0,  unit="mm"),
        ParamSpec("bump_start_pct",       value=35.0,  min=0.0,  max=100.0, unit="pct"),
        ParamSpec("bump_length_pct",      value=25.0,  min=0.0,  max=100.0, unit="pct"),
        ParamSpec("bump_height_mm",       value=15.0,  min=0.0,  max=150.0,  unit="mm"),
        ParamSpec("wall_thickness_mm",    value=2.0,   min=0.8,  max=15.0,   unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # A lofted, variably-tapered, ASYMMETRIC hollow shell isn't a single-solid plate/bar shape — the
    # validated cantilever FS methodology (packages/truth_plane/solvers/fs.py) isn't a faithful
    # re-use here, same call lofted_spindle.py/saddle_clamp.py already made for their own shapes.
    # FS honestly stays "unknown" for this part type.
    fea_eligible=False,
    # 2026-07-19 (airframe-first pacing) — same harmless over-inclusion reasoning as
    # lofted_spindle.py's own comment: a cross-industry hull/body shape that can act as a fuselage.
    # See prompt_builder.py's "airframe-first pacing" section.
    is_airframe_defining=True,
))
