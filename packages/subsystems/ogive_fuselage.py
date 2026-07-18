"""Ogive fuselage — a streamlined body-of-revolution primitive purpose-built for aircraft/rocket
fuselages, nacelles, and nose cones. `lofted_spindle.py`'s sibling, NOT a replacement: that file's
cosine-ease taper is the right curve for a bottle, a tool handle, a shaft — a curve that stays nearly
flat right at each tip before rounding into the body (a real bottle's shoulder-into-a-neck look). A
real aircraft fuselage nose/tail does the OPPOSITE: it flares away from the tip immediately (an
ogive/paraboloid nose cone) and a tailcone narrows to a real point rather than lingering at some
constant "neck" radius first.

CONFIRMED VISUAL BUG this session, diagnosed directly from a rendered screenshot: `winged_fuselage.py`
originally built its fuselage body via `lofted_spindle` (reused as-is). The user's own words: "it
looks like a squished bottle not a fuselage" — and looking at the actual render, that's EXACTLY right:
both tips showed a small flat cylindrical "neck" (most visible as a distinct circular rim right at the
blunt tail tip) before flaring into the body, because `ease_at`'s cosine smoothstep has ZERO slope at
every taper-zone boundary, tip included (see `_loft_profiles.py`'s `ease_at` docstring) — no amount of
re-tuning `lofted_spindle`'s existing params (tip radius, taper length) fixes this, since the flat-
near-the-tip behavior comes from the CURVE FAMILY itself, not from any one param's value. Changing
`lofted_spindle`'s own default curve was rejected: it's a shared, generically-useful primitive (also
used standalone for bottles/handles/shafts, per its own module docstring) with its own tests pinning
specific measured loft-vs-closed-form volume tolerances against the CURRENT cosine-ease curve — this
file exists instead so `lofted_spindle`/`lofted_hull` (and anything else already built on `ease_at`)
stay completely unaffected, while `winged_fuselage.py` (and any future aerospace-shaped-body use)
builds on a curve that actually looks like a fuselage. See `_loft_profiles.ogive_ease_at`'s own
docstring for the power-law formula and why `power < 1` (steep at the tip, flattening into the
plateau) is the fix.

SOLID, not hollow (2026-07-06, explicit user call): earlier this session this built a hollow shell,
sharing `lofted_spindle.py`'s outer-loft-minus-inner-loft technique. The user wants a SOLID body for
now — "we can use shell command on a fuselage later. For now just use a solid fuselage." So `_build()`
below is just the outer loft, full stop, no inner cavity loft/subtract, and there is no
`wall_thickness_mm` param to plumb through. Hollowing is explicitly DEFERRED to a future shell/hollow
operation (NOT built yet — `packages/ledger/deltas.py::FeatureOp` only supports `hole`/`pocket`/`slot`
today, no `shell` kind) applied on top of this solid body, not baked into this loft — do not re-add a
`wall_thickness_mm` param here without that explicit ask; `lofted_spindle.py` remains the place to look
for the outer-loft/inner-loft hollowing technique if it's needed again.

Volume-fidelity finding this session (mirrors `lofted_spindle.py`'s own disclosed-approximation
note): measured directly against `_volume`'s 200-step disk integration at this subsystem's default
(`taper_power=0.5`) params, the real built solid UNDERSHOOTS the closed-form estimate by ~13.1% at
`_N_TAPER_STATIONS=10` (the smooth B-spline loft rounds off the power-law curve's steep near-tip rise
rather than reproducing that sharp initial slope exactly) — re-measured directly again on 2026-07-18
while building `tube_fuselage.py` (this file's sibling): the actual figure is ~13%, not the ~5.4% this
docstring previously claimed (a stale number from earlier in this subsystem's development that was
never re-checked after a later change) — `test_volume_approximates_real_build_within_tolerance`'s own
enforced `< 0.15` bound is what actually matters and the current ~13% still clears it, so nothing
about the shipped behavior was ever wrong, only this comment's specific percentage. Checked directly
at higher station counts too: the gap does NOT monotonically shrink (n=16 -> -6.45%, n=24 -> -6.78%,
n=40 -> flips to +7.66%, likely loft instability rather than genuine convergence — `lofted_spindle.py`'s
own module docstring reports the same non-monotonic breakdown at high counts on its own curve) —
`_N_TAPER_STATIONS=10` is kept rather than chasing a count that doesn't converge.
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems._loft_profiles import ogive_ease_at, taper_stations

_FRAGMENT = """\
## Subsystem: Ogive fuselage
A streamlined body-of-revolution primitive for aircraft/rocket fuselages, nacelles, and nose cones —
`lofted_spindle`'s sibling, purpose-built so nose/tail tips flare away from the tip immediately (an
ogive/paraboloid nose, a tailcone narrowing to a real point) instead of `lofted_spindle`'s bottle-
shoulder-into-a-neck look. Reach for THIS subsystem (or `winged_fuselage`, which already uses it)
whenever the part is described as a fuselage, an airframe body, a nose cone, or a nacelle and no real
constant-diameter run/keel line is called for; reach for plain `lofted_spindle` for a bottle, a
handle, a shaft, or anything NOT meant to look aerodynamic; reach for `tube_fuselage` instead of THIS
subsystem specifically when the request describes an airliner-style body — distinct nose/parallel-
body/tail proportions (not one smooth taper start-to-end) or a flattened cargo-floor keel line.
SOLID, not hollow — no `wall_thickness_mm` param; a shell/hollow-out pass is a separate, not-yet-built
feature for later, not something this subsystem's loft does today.
- **length_mm** — overall length along the axis.
- **max_width_mm / max_height_mm** — cross-section size at the widest point (the plateau between the
  two tapers). Equal (the default) = circular; different = a flattened ellipse (a real fuselage's
  flatter belly/wider-than-tall cross-section).
- **start_taper_mm / end_taper_mm** — length of the nose/tail taper region. A real fuselage's nose
  taper is usually much SHORTER than its tail taper (a blunt nose, a long tapering tailcone/boattail).
- **start_width_mm / start_height_mm, end_width_mm / end_height_mm** — tip cross-section size at each
  end. 0/0 tapers all the way to a true point.
- **taper_power** — shape of the flare-away-from-the-tip curve. 0.5 (the default) is the classic
  tangent-ogive/half-power nose-cone profile (steep right at the tip, flattening into the barrel);
  1.0 is a plain straight cone; push above 1.0 for a thin, concave, pin-like taper instead (unusual,
  but not blocked).

### Intent mapping
- "a fuselage" / "a nose cone" / "an aircraft body" / "a nacelle" -> this subsystem (directly, or via
  `winged_fuselage` if a wing needs to fuse onto it too) — NOT `lofted_spindle`.
- "a blunter nose" / "a more pointed nose" -> decrease/increase `taper_power` (below/above 0.5).
- "a longer tail taper" / "a stubbier nose" -> increase `end_taper_mm` relative to `start_taper_mm`
  (or shorten `start_taper_mm`) — matches how a real fuselage's tailcone is usually longer than its
  nose taper.
- "flattened" / "not perfectly round" / "wider than it is tall" -> set `max_height_mm` below
  `max_width_mm` (or vice versa).\
"""

_N_TAPER_STATIONS = 10  # see module docstring: slightly denser than lofted_spindle's 8
_N_VOLUME_STEPS = 200  # midpoint-rule disk-integration steps for _volume (pure python, cheap)
_POINT_EPS_MM = 1e-6  # a station half-extent at/below this is treated as a true point (Vertex tip)


def _width_at(x: float, p) -> float:
    """Half-width (>= 0) at axial position x in [0, length_mm] — `ogive_ease_at` (power-law,
    `_loft_profiles.py`), NOT `lofted_spindle`'s `ease_at` (cosine-ease) — see module docstring."""
    x_a = p.start_taper_mm
    x_b = p.length_mm - p.end_taper_mm
    return ogive_ease_at(x, x_a, x_b, p.length_mm,
                         p.start_width_mm / 2.0, p.max_width_mm / 2.0, p.end_width_mm / 2.0,
                         power=p.taper_power)


def _height_at(x: float, p) -> float:
    """Half-height (>= 0) at axial position x — independent schedule from `_width_at()`, same
    power-law taper. Equal to `_width_at()` everywhere iff every width_mm param equals its height_mm
    counterpart (the default), which is exactly what keeps the default shape a true circle."""
    x_a = p.start_taper_mm
    x_b = p.length_mm - p.end_taper_mm
    return ogive_ease_at(x, x_a, x_b, p.length_mm,
                         p.start_height_mm / 2.0, p.max_height_mm / 2.0, p.end_height_mm / 2.0,
                         power=p.taper_power)


def _stations(p) -> list[tuple[float, float, float]]:
    """(x, width_half, height_half) triples along the axis for `_build()`'s outer loft — SAME
    `taper_stations()` sampler `lofted_spindle` uses (uniform-in-x within each taper zone); pure
    python (no build123d) so `_volume()` can reuse the exact same schedule."""
    xs = taper_stations(p.length_mm, p.start_taper_mm, p.end_taper_mm, _N_TAPER_STATIONS)
    return [(x, _width_at(x, p), _height_at(x, p)) for x in xs]


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart

    stations = _stations(p)

    def _section(x: float, w_half: float, h_half: float):
        # Vertex tip whenever EITHER half-extent collapses to ~0 — see lofted_spindle.py's identical
        # handling and module docstring for why a degenerate zero-area Ellipse is unsafe in bd.loft().
        if w_half <= _POINT_EPS_MM or h_half <= _POINT_EPS_MM:
            return bd.Vertex(x, 0, 0)
        # Rotation(0,90,0) maps local x_radius -> global Z half-extent, local y_radius -> global Y
        # half-extent (verified directly in lofted_spindle.py's own session), so height goes first.
        return bd.Pos(x, 0, 0) * (bd.Rotation(0, 90, 0) * bd.Ellipse(h_half, w_half))

    # SOLID — just the outer loft, no inner cavity loft/subtract. See module docstring: hollowing is
    # explicitly deferred to a future shell/hollow feature, not baked into this loft.
    solid = bd.loft([_section(x, w, h) for x, w, h in stations], ruled=False)

    return TaggedPart(solid, {
        "fuselage.body": {
            "kind": "solid", "length": p.length_mm,
            "max_width": p.max_width_mm, "max_height": p.max_height_mm,
        },
    })


def _volume(p) -> float:
    """Method-of-disks numerical integration over `_width_at()`/`_height_at()` — NOT a build123d
    call (the interactive plane is closed-form arithmetic only, no OCCT on that path, per
    CLAUDE.md). SOLID body — no inner-cavity subtraction (see module docstring). See module
    docstring for the measured disclosed-approximation error at defaults, same order of magnitude
    as `lofted_spindle`'s own disclosed figures."""
    dx = p.length_mm / _N_VOLUME_STEPS
    vol = 0.0
    for i in range(_N_VOLUME_STEPS):
        xm = (i + 0.5) * dx
        vol += math.pi * _width_at(xm, p) * _height_at(xm, p) * dx
    return max(0.0, vol)


def _check(p) -> list[str]:
    out: list[str] = []
    if p.start_taper_mm + p.end_taper_mm > p.length_mm:
        out.append(
            f"start_taper {p.start_taper_mm:.1f} mm + end_taper {p.end_taper_mm:.1f} mm exceeds "
            f"length {p.length_mm:.1f} mm — tapers overlap"
        )
    if not (0.0 <= p.start_width_mm < p.max_width_mm):
        out.append(f"start_width {p.start_width_mm:.1f} mm must be >= 0 and < max_width {p.max_width_mm:.1f} mm")
    if not (0.0 <= p.start_height_mm < p.max_height_mm):
        out.append(f"start_height {p.start_height_mm:.1f} mm must be >= 0 and < max_height {p.max_height_mm:.1f} mm")
    if not (0.0 <= p.end_width_mm < p.max_width_mm):
        out.append(f"end_width {p.end_width_mm:.1f} mm must be >= 0 and < max_width {p.max_width_mm:.1f} mm")
    if not (0.0 <= p.end_height_mm < p.max_height_mm):
        out.append(f"end_height {p.end_height_mm:.1f} mm must be >= 0 and < max_height {p.max_height_mm:.1f} mm")
    if p.taper_power <= 0.0:
        out.append(f"taper_power {p.taper_power:.2f} must be > 0")
    return out


OGIVE_FUSELAGE = register_subsystem(Subsystem(
    name="ogive_fuselage",
    description="Streamlined SOLID body-of-revolution for aircraft/rocket fuselages, nacelles, nose "
                "cones — power-law (ogive) nose/tail taper that flares from the tip immediately, "
                "not lofted_spindle's bottle-shoulder-into-a-neck cosine-ease curve",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",         value=400.0, min=50.0, max=3000.0, unit="mm"),
        ParamSpec("max_width_mm",      value=80.0,  min=10.0, max=800.0,  unit="mm"),
        ParamSpec("max_height_mm",     value=80.0,  min=10.0, max=800.0,  unit="mm"),
        ParamSpec("start_taper_mm",    value=80.0,  min=0.0,  max=1500.0, unit="mm"),
        ParamSpec("end_taper_mm",      value=150.0, min=0.0,  max=1500.0, unit="mm"),
        ParamSpec("start_width_mm",    value=8.0,   min=0.0,  max=400.0,  unit="mm"),
        ParamSpec("start_height_mm",   value=8.0,   min=0.0,  max=400.0,  unit="mm"),
        # Pointier than the nose — no min-wall floor to clear now that this body is solid (was
        # bumped up to 6.0 while this was still a hollow shell; back to a sharper 4.0 now).
        ParamSpec("end_width_mm",      value=4.0,   min=0.0,  max=400.0,  unit="mm"),
        ParamSpec("end_height_mm",     value=4.0,   min=0.0,  max=400.0,  unit="mm"),
        ParamSpec("taper_power",       value=0.5,   min=0.3,  max=2.0,    unit="ratio"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # A lofted, variably-tapered body of revolution isn't a single-solid plate/bar shape — the
    # validated cantilever FS methodology (packages/truth_plane/solvers/fs.py) isn't a faithful
    # re-use here, same honest "unknown" stance lofted_spindle.py/saddle_clamp.py already take.
    fea_eligible=False,
    # 2026-07-19 (airframe-first pacing) — a fuselage sets the vehicle's own outer mold line. See
    # prompt_builder.py's "airframe-first pacing" section.
    is_airframe_defining=True,
))
