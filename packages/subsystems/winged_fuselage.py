"""Winged fuselage — a composite subsystem: an `ogive_fuselage` body + a `naca_wing` panel,
BOOLEAN-FUSED into one continuous, printable wing-body solid (a real overlap at the wing root, not
just tangent contact — see `fuse()`, `packages/subsystems/compose.py`).

SQUISHED-BOTTLE BUG, fixed this session (real-shape regression, diagnosed directly from a rendered
screenshot after the user pushed back: "it looks like a squished bottle not a fuselage"): this file
used to build its fuselage body via `lofted_spindle`. That subsystem's cosine-ease taper has ZERO
slope right at each tip — correct for a bottle's shoulder-into-a-neck, wrong for an aircraft nose/tail,
which must flare away from the tip immediately. Switched to `ogive_fuselage` (this session's new
sibling subsystem, same hollow-shell loft technique, power-law taper instead) — see that file's own
module docstring for the full diagnosis. `lofted_spindle` itself was deliberately left untouched (it's
also used standalone for bottles/handles/shafts, with its own tests pinned to its own curve).

Uses the Phase F composition helpers (`call()`/`place()`/`fuse()`, `packages/subsystems/compose.py`)
directly in its OWN `build()`, unlike the later assembly-template composites (`table.py`,
`standoff_frame.py`) that materialize their children as separate sibling `Instance`s. That mechanism
is the right one when the parts are meant to stay independently addressable/exportable bodies (a
tabletop and its legs); it is the WRONG one here — the whole point of this subsystem is that the wing
and the fuselage become ONE manifold body (see `fuse()`'s docstring on why it exists as `compose()`'s
intentional opposite), so this file returns a single fused `TaggedPart` from a plain `build`, the same
shape every leaf subsystem in this catalog already has.

PARAMS: this subsystem's own `ParamSpec` list is the UNION of `ogive_fuselage`'s own params and
`naca_wing`'s own params (same "combine both sides' params into one flat block" pattern
`table.py`'s module docstring/`_children()` follows for its top+leg params) — declared fresh here
(not the child modules' own `ParamSpec` objects reused directly) so this subsystem's OWN default
values can describe a coherent small-aircraft/UAV proportion (a ~400mm fuselage carrying a ~500mm
wingspan) independent of whichever defaults `ogive_fuselage`/`naca_wing` pick for their own
standalone use — while keeping every param NAME identical to the child's own, since `call()`'s
override kwargs must match a child's declared param names exactly. PLUS two tag-only params
(`section_a_pct`/`section_b_pct`) with NO geometric effect at all — see `_build()`.

WING PLACEMENT / ROTATION MATH (read before changing `wing_position_pct`'s formula or the rotation
below): `naca_wing`'s own loft axis (span) is its LOCAL X (see that file's module docstring — the
same "loft axis is X" convention `lofted_spindle`/`lofted_hull`/`ogive_fuselage` already use for their
own length axis), built centered on its own local origin (`X` in `[-span_mm/2, +span_mm/2]`).
`ogive_fuselage`'s fuselage is built along GLOBAL X too (`X` in `[0, length_mm]`, per that file's own
station-x convention), so making the wing's span run PERPENDICULAR to the fuselage's long axis means
rotating
the wing's local X onto global Y — `bd.Rotation(0, 0, -90)` (a plain rotation about Z) does exactly
that (verified directly this session: a box built long along local X comes out long along global Y
after this rotation, with local Y mapping to global +X and local Z staying global Z unchanged).

SWEEP-SIGN BUG, fixed this session (real-shape regression, diagnosed from a build failing this file's
own `test_fuse_produces_one_real_manifold_not_two_touching_solids` volume check once nonzero
`sweep_deg`/forward `wing_position_pct` defaults were introduced): this rotation used to be `rz=+90`,
which maps `naca_wing`'s local +Y (its OWN "aft" direction — see that file's `_sweep_dihedral_offset`
docstring, positive `sweep_deg` shifts both tips toward local +Y) onto global **-X**, i.e. toward the
fuselage's NOSE (small X), the opposite of what "sweep aft" should mean once composed into this
fuselage's own nose-at-0/tail-at-length_mm convention. Silent at `sweep_deg=0.0` (no offset to get the
sign of wrong), it surfaces the moment sweep is nonzero AND `wing_position_pct` sits forward of
center: the tips get shifted (by the inverted sign) INTO the narrowing nose-taper zone rather than
away from it, and the resulting wing/fuselage overlap becomes complex enough that `fuse()`'s boolean
union — while still reporting `is_valid=True` and a single solid — produces an impossible
volume-greater-than-the-naive-sum result (a real self-intersection OCCT's validity check doesn't
catch). `rz=-90` fixes the sign so positive `sweep_deg` now sweeps toward the TAIL (+X) as
`naca_wing`'s own docstring promises, which also happens to shift swept tips AWAY from the narrow
nose zone instead of into it — verified directly across a range of sweep/dihedral/`wing_position_pct`
combinations (including this subsystem's own new defaults) that the fused volume now stays below the
naive sum in every case tried, not just at the exact default point.

Placing the rotated wing at `y=0, z=0` puts its own centerline (max chord/thickness, at local X=0)
exactly on the fuselage's own central axis (both `ogive_fuselage`'s Y and Z cross-section coordinates
are centered on 0 at every station — see that file's `_section()`) — AT THIS SUBSYSTEM'S DEFAULT
params, the wing's full span (hundreds of mm) is far larger than the fuselage's local half-width
(tens of mm), so the wing's own root region punches all the way through the fuselage's SOLID body on
BOTH sides (entering near `Y = -width_half(x)`, crossing the full local width, and exiting again near
`Y = +width_half(x)`) with substantial chordwise/thickness extent still present at each crossing
(verified directly in test_winged_fuselage.py) — this is what makes `fuse()`'s boolean union produce
ONE valid, single-solid manifold body rather than the wing sitting fully engulfed inside the
fuselage's solid material with no visible/structural change of its own.

THIS IS NOT A UNIVERSAL GUARANTEE OF THE PARAM SPACE, though — it was originally (wrongly) documented
as one here. `span_mm` and `max_width_mm` are independent params with independently declared
ParamSpec bounds, and a combination fully inside both (e.g. `span_mm` at its own 100mm floor with
`max_width_mm` only slightly above its own 80mm default, both at the default `wing_position_pct=50`)
can put the wing's half-span BELOW the fuselage's own half-width at the crossing station — the wing
then sits entirely embedded inside the fuselage's SOLID body, never reaching its own outer surface,
`fuse()`'s `+` silently produces a build where the wing contributes no visible feature and no
independent load path (still `is_valid=True`), and no exception is raised anywhere in the build path.
`_check()` below now cross-checks this directly (`_fuselage_width_half_at()`, the same closed-form
`ogive_ease_at` schedule `ogive_fuselage._width_at()` uses) so this failure mode surfaces as an
invariant violation instead of a silently-fabricated "it built fine" green light. `wing_position_pct`
(0-100% of `length_mm`) picks WHICH axial station along the fuselage this crossing happens at; the
default (38.0, ahead of the waist — see the SQUISHED-BOTTLE BUG / nose-tail-asymmetry notes above)
still lands inside `ogive_fuselage`'s own widest plateau zone at this subsystem's default fuselage
taper params, for a generous overlap margin — but a generous DEFAULT does not make the crossing
self-guaranteeing across the whole declared param space, hence the explicit check.
"""

from __future__ import annotations

from packages.subsystems import ParamSpec, Subsystem, call, fuse, place, register_subsystem
from packages.subsystems._loft_profiles import ogive_ease_at
from packages.subsystems.ogive_fuselage import OGIVE_FUSELAGE
from packages.subsystems.naca_wing import NACA_WING

_FRAGMENT = """\
## Subsystem: Winged fuselage (composite, fused)
A streamlined ogive fuselage body (see `ogive_fuselage`) with a full-span NACA wing panel (see
`naca_wing`) BOOLEAN-FUSED onto it at one axial station — one continuous, printable wing-body OML
shell, not two touching parts. This combines every `ogive_fuselage` param and every `naca_wing` param
into one flat block (see each of those subsystems' own fragments for what each param does) PLUS:
- **wing_position_pct** — where along the fuselage (0-100% of length_mm) the wing crosses through,
  rotated so its span runs perpendicular to the fuselage's long axis. Default 42 puts the wing ahead
  of the waist, leaving a distinctly longer tail section aft of it than the nose section ahead of it.
- **section_a_pct / section_b_pct** — two axial reference stations (0-100% of length_mm), written
  into the part's tags as INERT metadata only (e.g. future bulkhead-cut positions) — they have NO
  geometric effect on the built solid; nothing is actually cut there yet.

Be honest about the limits of this, same disclosure this engine already gives for any composed
assembly (see the satellite/UAV caveat elsewhere in this prompt): fusing a real lofted fuselage to a
real NACA-section wing gives you grounded, dimensioned, FEA-checkable-elsewhere-in-principle
STRUCTURAL geometry — it is pure geometry, with NO aerodynamic performance claim attached (no CFD, no
XFOIL, no lift/drag/stability number of any kind). If the user asks for flight performance on top of
this shape, say plainly that it's out of scope rather than fabricating an answer.

### Intent mapping
- "a wing fused to the fuselage" / "one continuous body" / "make it printable as one part" -> this
  subsystem, not a separately-placed `ogive_fuselage` + `naca_wing` pair.
- "move the wing forward/aft" -> decrease/increase wing_position_pct.
- "mark bulkhead stations at 30% and 70%" -> set section_a_pct/section_b_pct accordingly (metadata
  only — pair with an actual `bulkhead_frame` instance if a real physical bulkhead is wanted there).\
"""

# This subsystem's OWN param list — the union of ogive_fuselage's + naca_wing's own param NAMES
# (kept letter-for-letter identical to each child's own ParamSpec names, since call()'s override
# kwargs below must match exactly), with fresh default VALUES sized for a coherent small-
# aircraft/UAV proportion (see module docstring), plus the two tag-only section params.
_FUSELAGE_PARAMS = [
    ParamSpec("length_mm",         value=400.0, min=100.0, max=2000.0, unit="mm"),
    ParamSpec("max_width_mm",      value=80.0,  min=20.0,  max=500.0,  unit="mm"),
    ParamSpec("max_height_mm",     value=60.0,  min=20.0,  max=500.0,  unit="mm"),
    ParamSpec("start_taper_mm",    value=80.0,  min=0.0,   max=1000.0, unit="mm"),
    ParamSpec("end_taper_mm",      value=150.0, min=0.0,   max=1000.0, unit="mm"),
    # Small (not the old lofted_spindle 15/10) — ogive_fuselage's power-law taper already flares
    # away from the tip immediately, so the tip itself doesn't need a big blunt radius to avoid
    # looking like a bottle neck (see ogive_fuselage.py's module docstring / the SQUISHED-BOTTLE
    # BUG note above). Nose still slightly blunter than tail, matching a real fuselage.
    ParamSpec("start_width_mm",    value=8.0,   min=0.0,   max=500.0,  unit="mm"),
    ParamSpec("start_height_mm",   value=8.0,   min=0.0,   max=500.0,  unit="mm"),
    ParamSpec("end_width_mm",      value=6.0,   min=0.0,   max=500.0,  unit="mm"),
    ParamSpec("end_height_mm",     value=6.0,   min=0.0,   max=500.0,  unit="mm"),
    # No wall_thickness_mm — ogive_fuselage is a SOLID body (2026-07-06 explicit user call, see that
    # file's own module docstring); do not re-add this param without a real shell/hollow feature to
    # plumb it into.
    # 0.5 = the classic tangent-ogive/half-power nose-cone profile (see ogive_fuselage.py) — steep
    # right at each tip, flattening into the barrel; this is the param that actually fixes the
    # "squished bottle" look, not just a tip-radius tweak.
    ParamSpec("taper_power",       value=0.5,   min=0.3,   max=2.0,    unit="ratio"),
]
_WING_PARAMS = [
    ParamSpec("span_mm",        value=500.0, min=100.0, max=3000.0, unit="mm"),
    ParamSpec("root_chord_mm",  value=120.0, min=20.0,  max=600.0,  unit="mm"),
    ParamSpec("tip_chord_mm",   value=60.0,  min=10.0,  max=600.0,  unit="mm"),
    ParamSpec("thickness_pct",  value=12.0,  min=6.0,   max=21.0,   unit="pct"),
    # Aft sweep + a shallow dihedral (both were 0.0 — a perpendicular, dead-flat panel) so the default
    # silhouette reads as a swept aircraft wing rather than a straight crossbar; see module docstring's
    # "WING PLACEMENT / ROTATION MATH" note. RE-TUNED after switching the fuselage body to
    # `ogive_fuselage`: that curve has a nonzero (not zero, unlike `lofted_spindle`'s cosine-ease)
    # slope right at the plateau boundary, so it narrows MORE aggressively just past the plateau —
    # the previous 20°/dihedral-5°/pos-38% combo (tuned against the old `lofted_spindle` body) left
    # only a hair's-breadth-to-negative fuse() volume margin against the new body's faster taper.
    # 12°/5°/pos-42% was verified directly (this session) to hold a healthy ~3% margin at THIS
    # subsystem's default `wing_position_pct` — `_check()`'s half-span-vs-half-width cross-check
    # still only validates the ROOT crossing station, not a swept wing's full fore/aft reach, so this
    # is a verified-at-the-shipped-default tuning, not a proof that every reachable param combination
    # stays this comfortable.
    ParamSpec("sweep_deg",      value=12.0,  min=-30.0, max=45.0,   unit="deg"),
    ParamSpec("dihedral_deg",   value=5.0,   min=-10.0, max=20.0,   unit="deg"),
]
_PLACEMENT_PARAMS = [
    # Forward of the fuselage's own midpoint (was 50.0, "the waist") so a distinctly longer tail
    # section extends aft of the wing than the nose section extends ahead of it — the single biggest
    # lever for reading as "an airplane" rather than a symmetric X/shuriken cross (see conversation:
    # the default 50/50 split, combined with a 0-sweep wing, made both arms of the cross equally
    # weighted with no nose/tail asymmetry visible). Still comfortably inside the fuselage's own
    # [start_taper_mm, length_mm - end_taper_mm] plateau at every default fuselage param, so the
    # crossing-margin invariant below is unaffected. 42 (not 38 — see the sweep_deg note above) after
    # re-tuning against the new `ogive_fuselage` body's own margin sensitivity.
    ParamSpec("wing_position_pct", value=42.0, min=0.0, max=100.0, unit="pct"),
]
# Tag-only — see module docstring and _build(): written verbatim into the returned part's tags,
# with NO geometric effect whatsoever.
_SECTION_TAG_PARAMS = [
    ParamSpec("section_a_pct", value=30.0, min=0.0, max=100.0, unit="pct"),
    ParamSpec("section_b_pct", value=70.0, min=0.0, max=100.0, unit="pct"),
]

_FUSELAGE_PARAM_NAMES = [spec.name for spec in _FUSELAGE_PARAMS]
_WING_PARAM_NAMES = [spec.name for spec in _WING_PARAMS]

# Minimum required "punch-through" margin (mm) the wing's half-span must clear BEYOND the fuselage's
# own outer half-width at the crossing station (see _check()'s cross-check below) — a buffer against
# knife-edge, near-zero-measure overlaps that a real boolean union can't reliably collapse to one
# manifold solid (float/tessellation noise near an exact tangency), not a precise physical bound.
_MIN_CROSSING_MARGIN_MM = 5.0


def _fuselage_width_half_at(x: float, p) -> float:
    """Fuselage half-width (its Y half-extent, the crossing axis after the wing's `rz=-90` rotation —
    see module docstring) at fuselage-axial position `x` — the SAME power-law schedule
    `ogive_fuselage._width_at()` uses (`ogive_ease_at`, `_loft_profiles.py`), reproduced here rather
    than imported as a private cross-module call, since this composite's own `Namespace` already
    carries every fuselage param name `ogive_ease_at` needs (see the union-of-params note in the
    module docstring). Used ONLY by `_check()`'s wing/fuselage crossing cross-check below — `_build()`
    still delegates the actual fuselage geometry to `ogive_fuselage` itself via `call()`, this is a
    closed-form cross-check only, not a second geometry path."""
    x_a = p.start_taper_mm
    x_b = p.length_mm - p.end_taper_mm
    return ogive_ease_at(x, x_a, x_b, p.length_mm,
                         p.start_width_mm / 2.0, p.max_width_mm / 2.0, p.end_width_mm / 2.0,
                         power=p.taper_power)


def _build(p):
    fuselage_part = call("ogive_fuselage", **{name: getattr(p, name) for name in _FUSELAGE_PARAM_NAMES})
    wing_part = call("naca_wing", **{name: getattr(p, name) for name in _WING_PARAM_NAMES})

    # See module docstring's "WING PLACEMENT / ROTATION MATH" section for why rz=-90 / y=0 / z=0 is
    # what guarantees a real, non-degenerate 3D overlap with the fuselage shell rather than mere
    # tangent contact — and why rz must be -90, not +90 (the SWEEP-SIGN BUG note): +90 maps positive
    # sweep_deg toward the nose instead of the tail.
    wing_x = p.length_mm * p.wing_position_pct / 100.0
    wing_placed = place(wing_part, x=wing_x, y=0.0, z=0.0, rz=-90.0)

    fused = fuse(fuselage=fuselage_part, wing=wing_placed)

    # Two INERT reference-station tags — pure metadata, no geometric effect (no cut, no feature, no
    # solid change of any kind). A later phase can read these back to place a real bulkhead cut.
    fused.tags["fuselage.section_a"] = {
        "kind": "reference_station",
        "z_mm": p.length_mm * p.section_a_pct / 100.0,
        "note": "bulkhead reference station — inert metadata, not yet cut",
    }
    fused.tags["fuselage.section_b"] = {
        "kind": "reference_station",
        "z_mm": p.length_mm * p.section_b_pct / 100.0,
        "note": "bulkhead reference station — inert metadata, not yet cut",
    }
    return fused


def _volume(p) -> float:
    """Sum of the two children's own closed-form volume estimators — both are plain
    `Namespace -> float` callables (`Subsystem.volume`), and this composite's OWN `Namespace` already
    carries every attribute name either one reads (see the param lists above), so each can be called
    directly with `p` itself, no separate sub-`Namespace` construction needed.

    Disclosed APPROXIMATION, not fabricated: a naive sum overstates the true fused volume by the
    (real, but not cheap to compute in closed form here) region where the wing root and the fuselage
    shell wall genuinely overlap (see `_build()` / module docstring) — the boolean union in the real
    build does NOT double-count that overlap, but this fast closed-form estimate does. Same "a few
    percent" disclosed-error stance `ogive_fuselage.py`/`naca_wing.py`'s own `_volume()` docstrings
    already take relative to their real builds."""
    return OGIVE_FUSELAGE.volume(p) + NACA_WING.volume(p)


def _check(p) -> list[str]:
    """Reuses each child's OWN invariant checks verbatim (both are plain `Namespace -> list[str]`
    callables) — this composite's `Namespace` is a superset of what either one reads, so no
    remapping is needed, and neither child's rule can silently drift out of sync with a
    separately-copy-pasted version here — PLUS one cross-check neither child can make on its own:
    that the wing's half-span actually reaches past the fuselage's own outer half-width at the axial
    station where it crosses (see module docstring and `_fuselage_width_half_at()`). Without this,
    `fuse()`'s boolean union can silently engulf the wing entirely inside the fuselage's SOLID body
    (never reaching its own outer surface) rather than producing one real fused manifold body with a
    visible wing feature — reachable for parameter combinations fully inside every declared ParamSpec
    bound (e.g. `span_mm` at its own 100mm floor combined with `max_width_mm` only slightly above its
    own 80mm default, both at the default `wing_position_pct=50`), with no other signal (`is_valid`
    still reads `True`)."""
    out = OGIVE_FUSELAGE.invariants(p) + NACA_WING.invariants(p)
    wing_x = p.length_mm * p.wing_position_pct / 100.0
    fuselage_half_width = _fuselage_width_half_at(wing_x, p)
    wing_half_span = p.span_mm / 2.0
    required_half_span = fuselage_half_width + _MIN_CROSSING_MARGIN_MM
    if wing_half_span < required_half_span:
        out.append(
            f"wing half-span {wing_half_span:.1f} mm does not clear the fuselage's own half-width "
            f"{fuselage_half_width:.1f} mm (+ {_MIN_CROSSING_MARGIN_MM:.0f} mm required margin) at "
            f"the wing_position_pct={p.wing_position_pct:.0f}% crossing station (x={wing_x:.1f} mm) "
            f"— the wing would sit entirely embedded inside the fuselage's solid body without ever "
            f"reaching its own outer surface, so fuse() cannot produce a real fused manifold with a "
            f"visible wing feature; increase span_mm, decrease max_width_mm, or move "
            f"wing_position_pct to a narrower fuselage station"
        )
    return out


WINGED_FUSELAGE = register_subsystem(Subsystem(
    name="winged_fuselage",
    description="Ogive fuselage + full-span NACA wing panel, BOOLEAN-FUSED into one continuous "
                "printable wing-body solid — pure geometry, no aerodynamic performance claim",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[*_FUSELAGE_PARAMS, *_WING_PARAMS, *_PLACEMENT_PARAMS, *_SECTION_TAG_PARAMS],
    build=_build,
    volume=_volume,
    invariants=_check,
    # Neither child qualifies for the validated cantilever FS methodology on its own (see
    # ogive_fuselage.py/naca_wing.py's own fea_eligible notes), and a fused wing-body compound
    # shape certainly doesn't either. FS honestly stays "unknown" for this part type.
    fea_eligible=False,
))
