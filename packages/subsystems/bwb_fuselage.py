"""BWB fuselage — a blended-wing-body: ONE continuous full-span loft, thick "bulgy" airfoil cross-
sections at the centerline (the blended body/cabin volume) smoothly tapering, BOTH chord and
thickness_pct together, out to thin, normal wing-like airfoil tips. `naca_wing.py`'s sibling — same
`_naca_airfoil.naca4_profile_points` chordwise cross-section this whole file family already shares
("the final airfoil point from the wing itself", per the user's own description of how a real BWB is
built), but a DIFFERENT spanwise schedule and loft mode, for a reason specific to what a BWB actually
is (see below).

Second half of this session's two-part fuselage ask ("both, tube-style first, reuse the same
plumbing for BWB right after") — `tube_fuselage.py` built the airliner-tube half. The shared plumbing
that ACTUALLY carries over here is not `tube_fuselage.py`'s own `_cross_sections.py` (that's
ellipse/keel-specific, meaningless for an airfoil profile) but the two more general pieces every
lofted-body subsystem in this package already shares: `_loft_profiles.ease_at`/`taper_stations`
(the SAME "thick middle, taper to both ends" cosine-ease schedule `lofted_spindle.py` uses for its
own body) and `_naca_airfoil.naca4_profile_points` (the SAME airfoil point generator `naca_wing.py`
uses for its own wing panel) — composed together in a way neither existing file does on its own.

WHY `ease_at` (cosine-ease), not `naca_wing.py`'s plain-linear `_chord_at()` or `ogive_fuselage.py`'s
power-law `ogive_ease_at`: a real BWB's whole design premise is that the body and wing are ONE
continuous surface with no panel break — the transition must be smooth (zero-slope-into-the-plateau),
which is exactly `ease_at`'s shape and exactly the opposite of what a conventional wing wants
(`naca_wing.py`'s own module docstring: a real straight-tapered wing's leading/trailing edges are
STRAIGHT lines meeting at a sharp point at the root, which is why that file deliberately moved AWAY
from `ease_at` to a plain linear taper). `ogive_ease_at`'s "flares away from the tip immediately" curve
is also wrong here for the same reason in reverse: that shape exists specifically so a fuselage
nose/tail does NOT look like a smooth blend (see `ogive_fuselage.py`'s own module docstring) — the
one shape BWB explicitly wants.

WHY `ruled=False` (smooth B-spline loft), not `naca_wing.py`'s `ruled=True`: same reasoning as the
curve choice — `ruled=True` (straight-line elements between stations) is what gives a conventional
wing its sharp, flat-faceted taper; a BWB wants the smooth continuous surface `ruled=False` produces,
matching `lofted_spindle.py`/`ogive_fuselage.py`'s own body-of-revolution choice, not `naca_wing.py`'s
wing-panel choice.

Verified directly in build123d 0.10.0 this session, swept across station counts 6-20 (same rigor as
`tube_fuselage.py`'s own station-count sweep): valid, single-solid, and the closed-form estimate
(disk-integrated `_naca_airfoil.naca4_half_thickness` area, exactly mirroring `naca_wing.py`'s own
`_airfoil_area`) stayed under ~1% error THE ENTIRE SWEEP — far tighter than `tube_fuselage.py`'s own
~13-21% (an airfoil cross-section is much thinner relative to its chord than a fat elliptical tube is
relative to its diameter, so there is much less smooth-loft-vs-sampled-station bulge to begin with).
Also checked directly: `blend_taper_mm` at its own upper invariant bound (no flat centerbody span left
at all — the whole body is one continuous taper) and a combined sweep+dihedral case both still build
one valid solid.

SOLID, not hollow — same "shell it later" deferral every other lofted-body subsystem in this package
already carries (no hollowing feature exists yet, see `ogive_fuselage.py`'s own module docstring).
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems._loft_profiles import ease_at, taper_stations
from packages.subsystems._naca_airfoil import (
    naca4_half_thickness,
    naca4_profile_points,
    sweep_dihedral_offset,
)

_FRAGMENT = """\
## Subsystem: BWB fuselage
A blended-wing-body: ONE continuous full-span loft (tip-to-tip, not a separate body + attached wing)
through REAL NACA 4-digit symmetric airfoil cross-sections (`_naca_airfoil.py`, the same profile
family `naca_wing` uses) — thick and "bulgy" at the centerline (the blended body/cabin volume),
smoothly tapering, both chord AND thickness_pct together, out to thin, normal wing-like tips. SOLID,
not hollow. Reach for THIS subsystem specifically when the request describes a blended-wing-body,
flying-wing, or "the fuselage and wing are one shape" — reach for `tube_fuselage` instead when a
distinct round/tube-like body with its own separate wing attachment is wanted, or plain `naca_wing`
for a conventional wing panel with no thick center body at all.
- **span_mm** — full tip-to-tip span.
- **centerbody_chord_mm / centerbody_thickness_pct** — chord and max-thickness-as-%-of-chord AT THE
  CENTERLINE — the thick, deep section that gives the body its cabin/cargo volume. A real BWB's
  centerbody is much thicker than a normal wing (20-30%+ vs. a wing's usual 10-15%).
  centerbody_thickness_pct is the "12" in "NACA0012" terms, held at the centerline only.
- **tip_chord_mm / tip_thickness_pct** — chord and thickness_pct at each tip — normal, thin, wing-like
  proportions (must both be less than their centerbody counterparts: a BWB blends FROM a thick body
  TO a thin tip, never the reverse).
- **blend_taper_mm** — length of the smooth transition zone from the centerbody's own edge out to
  each tip (same value both sides). Whatever span is left over (`span_mm - 2 * blend_taper_mm`) is
  the flat centerbody plateau — a longer `blend_taper_mm` relative to `span_mm` means less flat
  centerbody and a more gradual, wing-like blend; `blend_taper_mm == span_mm / 2` means no flat
  centerbody at all (the whole body is one continuous taper from centerline to tip).
- **sweep_deg / dihedral_deg** — same meaning as `naca_wing`'s own params: sweep shifts each
  cross-section aft proportional to its distance from the centerline (positive = aft); dihedral
  shifts it up the same way (positive = both sides rise).

### Intent mapping
- "a blended wing body" / "a flying wing" / "the body and wing are one shape" -> this subsystem.
- "a bigger cabin" / "more internal volume" -> increase centerbody_chord_mm and/or
  centerbody_thickness_pct.
- "a more gradual blend" / "less of a distinct body" -> increase blend_taper_mm (toward span_mm / 2).
- "a sharper, more distinct centerbody" -> decrease blend_taper_mm (more flat centerbody span left
  over relative to span_mm).
- "swept" -> increase sweep_deg (positive = aft), same convention as naca_wing.\
"""

_MIN_WALL_MM = 0.8  # FDM min-wall floor, packages/ledger/apply.py::MIN_WALL_MM

_N_TAPER_STATIONS = 10  # matches tube_fuselage.py's own count -- see module docstring: error stayed
                        # under ~1% across a 6-20 sweep, so this is not a sensitive knob here either.
_N_VOLUME_STEPS = 200
_AREA_INTEGRATION_STEPS = 50
_POINT_EPS_MM = 1e-6


def _chord_at(dist_from_center: float, p) -> float:
    x_a = p.blend_taper_mm
    x_b = p.span_mm - p.blend_taper_mm
    return ease_at(dist_from_center, x_a, x_b, p.span_mm,
                    p.tip_chord_mm, p.centerbody_chord_mm, p.tip_chord_mm)


def _thickness_pct_at(dist_from_center: float, p) -> float:
    x_a = p.blend_taper_mm
    x_b = p.span_mm - p.blend_taper_mm
    return ease_at(dist_from_center, x_a, x_b, p.span_mm,
                    p.tip_thickness_pct, p.centerbody_thickness_pct, p.tip_thickness_pct)


def _stations(p) -> list[float]:
    """Loft-axis (X) sample positions, CENTERED on the body's own local origin — X in
    `[-span_mm/2, +span_mm/2]`. Reuses `taper_stations()` exactly as `lofted_spindle`/`ogive_fuselage`
    do for THEIR own start-taper/plateau/end-taper axis (`[0, length]`), then re-centers the result —
    a BWB's own "tip flare-in / flat centerbody / tip flare-out" shape is the identical zone structure,
    just symmetric about the middle rather than asymmetric start/end."""
    xs = taper_stations(p.span_mm, p.blend_taper_mm, p.blend_taper_mm, _N_TAPER_STATIONS)
    half = p.span_mm / 2.0
    return [x - half for x in xs]


def _section_points(x: float, p) -> list[tuple[float, float, float]]:
    dist = abs(x)
    chord = _chord_at(dist, p)
    tpct = _thickness_pct_at(dist, p)
    y_offset, z_offset = sweep_dihedral_offset(dist, p.sweep_deg, p.dihedral_deg)
    return naca4_profile_points(x, chord, tpct, 20, y_offset=y_offset, z_offset=z_offset)


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart

    stations = _stations(p)

    def _section(x: float):
        dist = abs(x)
        chord = _chord_at(dist, p)
        if chord <= _POINT_EPS_MM:
            y_offset, z_offset = sweep_dihedral_offset(dist, p.sweep_deg, p.dihedral_deg)
            return bd.Vertex(x, y_offset, z_offset)
        pts = _section_points(x, p)
        edge = bd.Spline(*pts, periodic=True)
        return bd.Face(bd.Wire([edge]))

    # ruled=False: a smooth B-spline surface through all stations -- the continuous, seamless blend
    # a BWB is defined by, NOT naca_wing.py's ruled=True straight-taper wing panel. See module
    # docstring for why this is the opposite choice from that sibling, deliberately.
    solid = bd.loft([_section(x) for x in stations], ruled=False)

    return TaggedPart(solid, {
        "bwb.body": {
            "kind": "solid", "span": p.span_mm,
            "centerbody_chord": p.centerbody_chord_mm, "tip_chord": p.tip_chord_mm,
            "sweep_deg": p.sweep_deg, "dihedral_deg": p.dihedral_deg,
        },
    })


def _airfoil_area(chord: float, thickness_pct: float, n: int = _AREA_INTEGRATION_STEPS) -> float:
    """Identical technique to `naca_wing._airfoil_area` — a midpoint-rule integral of
    `2 * naca4_half_thickness(x)` over `[0, chord]`."""
    if chord <= 1e-9:
        return 0.0
    dx = chord / n
    area = 0.0
    for i in range(n):
        xm = (i + 0.5) * dx
        area += 2.0 * naca4_half_thickness(xm, chord, thickness_pct) * dx
    return area


def _volume(p) -> float:
    """Method-of-disks numerical integration along the span — NOT a build123d call (interactive plane
    stays closed-form-only per CLAUDE.md). Measured directly against the real build (see module
    docstring): under ~1% error across a 6-20 station-count sweep at this subsystem's own defaults —
    much tighter than `tube_fuselage.py`'s disclosed ~13-21%, because an airfoil section is thin
    relative to its chord, leaving little room for the smooth loft to bulge past the sampled stations."""
    dx = p.span_mm / _N_VOLUME_STEPS
    half_span = p.span_mm / 2.0
    vol = 0.0
    for i in range(_N_VOLUME_STEPS):
        xm = (i + 0.5) * dx - half_span
        dist = abs(xm)
        vol += _airfoil_area(_chord_at(dist, p), _thickness_pct_at(dist, p)) * dx
    return max(0.0, vol)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.span_mm <= 0.0:
        out.append(f"span_mm {p.span_mm:.1f} mm must be > 0")
    if p.centerbody_chord_mm <= 0.0:
        out.append(f"centerbody_chord_mm {p.centerbody_chord_mm:.1f} mm must be > 0")
    if p.tip_chord_mm <= 0.0:
        out.append(f"tip_chord_mm {p.tip_chord_mm:.1f} mm must be > 0")
    if p.centerbody_thickness_pct <= 0.0:
        out.append(f"centerbody_thickness_pct {p.centerbody_thickness_pct:.1f}% must be > 0")
    if p.tip_thickness_pct <= 0.0:
        out.append(f"tip_thickness_pct {p.tip_thickness_pct:.1f}% must be > 0")
    if 2.0 * p.blend_taper_mm > p.span_mm:
        out.append(
            f"blend_taper_mm {p.blend_taper_mm:.1f} mm doubled exceeds span {p.span_mm:.1f} mm -- "
            f"the two taper zones overlap, leaving no room for a centerbody"
        )
    # Same reversed-taper blind spot naca_wing.py's own _check() was fixed for this session (see that
    # file's module docstring and build-plan/reference/AIRCRAFT_DESIGN_PROCESS.md §5): a BWB blends
    # FROM a thick centerbody TO a thin tip, never the reverse, and this is invisible to any aggregate
    # integral (wing area, volume) -- must be checked pointwise, on both chord AND thickness_pct
    # independently, not just one.
    if p.tip_chord_mm > p.centerbody_chord_mm:
        out.append(
            f"tip_chord_mm {p.tip_chord_mm:.1f} mm is larger than centerbody_chord_mm "
            f"{p.centerbody_chord_mm:.1f} mm -- a BWB must blend from a thick centerbody to a thin "
            f"tip, never the reverse"
        )
    if p.tip_thickness_pct > p.centerbody_thickness_pct:
        out.append(
            f"tip_thickness_pct {p.tip_thickness_pct:.1f}% is larger than centerbody_thickness_pct "
            f"{p.centerbody_thickness_pct:.1f}% -- a BWB must blend from a thick centerbody to a thin "
            f"tip, never the reverse"
        )
    # Tightest real thickness is at the tip (by construction, given the two checks above hold) --
    # same relationship naca_wing.py's own analogous check reuses (max thickness IS thickness_pct% of
    # the local chord, by the NACA 4-digit definition).
    if p.tip_chord_mm > 0.0 and p.tip_thickness_pct > 0.0:
        tip_thickness_mm = p.tip_chord_mm * p.tip_thickness_pct / 100.0
        if tip_thickness_mm < _MIN_WALL_MM:
            out.append(
                f"tip_thickness_pct {p.tip_thickness_pct:.1f}% of tip_chord_mm {p.tip_chord_mm:.1f} mm "
                f"gives only {tip_thickness_mm:.2f} mm max thickness at the tip -- need >= "
                f"{_MIN_WALL_MM} mm"
            )
    return out


BWB_FUSELAGE = register_subsystem(Subsystem(
    name="bwb_fuselage",
    description="Blended-wing-body — ONE continuous full-span loft, thick airfoil centerbody "
                "smoothly tapering (chord + thickness_pct together) to thin wing-like tips, solid",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("span_mm",                  value=800.0,  min=200.0, max=3000.0, unit="mm"),
        ParamSpec("centerbody_chord_mm",       value=300.0, min=50.0,  max=1500.0, unit="mm"),
        ParamSpec("tip_chord_mm",              value=80.0,  min=10.0,  max=600.0,  unit="mm"),
        ParamSpec("centerbody_thickness_pct",  value=28.0,  min=15.0,  max=40.0,   unit="pct"),
        ParamSpec("tip_thickness_pct",         value=12.0,  min=6.0,   max=21.0,   unit="pct"),
        ParamSpec("blend_taper_mm",            value=300.0, min=0.0,   max=1500.0, unit="mm"),
        ParamSpec("sweep_deg",                 value=25.0,  min=-30.0, max=45.0,   unit="deg"),
        ParamSpec("dihedral_deg",              value=0.0,   min=-10.0, max=20.0,   unit="deg"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # A lofted, variably-tapered body isn't a single-solid plate/bar shape -- the validated cantilever
    # FS methodology (packages/truth_plane/solvers/fs.py) isn't a faithful re-use here, same honest
    # "unknown" stance every other lofted-body subsystem in this package already takes.
    fea_eligible=False,
))
