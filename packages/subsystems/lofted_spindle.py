"""Lofted spindle — a general body-of-revolution subsystem (loft + hollow shell).

A generic, non-aerospace-specific primitive: thick in the middle, tapering at both ends. The same
shape family behind a bottle, a tool handle, a furniture spindle, a rocket body, a shaft — reusable
across product design, furniture, and machine design, not hard-coded to any single industry's
naming. Every other subsystem in this catalog extrudes ONE fixed profile then boolean-subtracts
holes; this is the first one that lofts between varying cross-sections.

Build123d 0.10.0 findings from this session (see also test_lofted_spindle.py):
- `bd.loft(sections, ruled=False)` smooth-lofts between any number of circular profiles; a
  `bd.Vertex(x, 0, 0)` may stand in as the first/last section to taper to a true point.
- `bd.offset(solid, amount=-wall)` does NOT hollow a fully-closed solid (no `openings`). Verified
  directly: offsetting a 20x20x20 box by -2mm with no openings returns volume 16**3 = 4096 (the
  solid shrunk inward), not 20**3 - 16**3 = 3904 (the hollow-shell answer) — it is a plain inward
  boundary offset, not a shell/thick-solid operation, unless a real opening face is supplied. Worse,
  on a loft with a Vertex-point tip, the fully-closed path either raises a recoverable
  `OCP.Standard_ConstructionError` (one pointed tip) or SEGFAULTS THE PROCESS outright (both tips
  pointed — reproduced with `openings=None`, `openings=[]`, and every `Kind`). None of this is safe
  to ship. `_build` below hollows via an INNER loft (radii reduced by `wall_thickness_mm`, clamped
  away from any station that would go non-positive) subtracted from the outer loft instead — a
  standard, robust technique that sidesteps `bd.offset`'s thick-solid code path entirely.
- The smooth loft overshoots the closed-form cosine-taper volume by more than the ~0.6% this
  session's plan text anticipated: measured directly against `_volume`'s 200-step disk integration,
  the REAL built shell (`_build`) comes in ~3.7% over at this subsystem's default (gentle-taper)
  params, ~4.9% over at a blunt-both-ends (15mm tip) config, and ~9.1% over at the
  fully-pointed-both-ends (0mm tip) extreme — the individual outer-loft and cavity-loft solids each
  overshoot their closed-form targets by a good deal more on their own (measured ~20% for the outer
  solid alone at the fully-pointed extreme), but the two overshoots partially cancel in the
  outer-minus-cavity subtraction since both lofts bulge by a similar proportion. `_N_TAPER_STATIONS`
  was bumped from the plan's suggested 5-6 to 8 to bring this down near "a few percent"; higher
  counts were not pursued further after a station count of 50 (on the fully-pointed profile)
  silently produced a self-intersecting solid that still reported `is_valid=True`. These volume
  figures were measured on the circular case and still apply unchanged there (this subsystem's
  default keeps `max_height_mm == max_width_mm`, i.e. a true circle) — the elliptical option added
  below reuses the identical loft technique, just with an independent width/height schedule.

Elliptical-flatten findings added this session (see also the module docstring for the new sibling
`lofted_hull.py`, which needed the same `bd.Ellipse` family more heavily):
- `bd.Ellipse(x_radius, y_radius, rotation=0, align=..., mode=...)` (`objects_sketch.py`, right next
  to `Circle`, same `Face(Wire.make_ellipse(...))` construction family) mixes freely with `Circle` in
  the same `bd.loft()` call and lofts cleanly against stations of any point count — verified
  directly. Placed the SAME way this file already places `Circle` — `bd.Pos(x, 0, 0) *
  (bd.Rotation(0, 90, 0) * bd.Ellipse(rx, ry))` — the rotation maps local `x_radius` onto the global
  Z half-extent and local `y_radius` onto the global Y half-extent (checked directly:
  `Rotation(0,90,0) * Ellipse(5, 10)` bounding-boxes to Y size 20 / Z size 10) — so `_section()`
  below passes `(height_half, width_half)` in that order.
- A `bd.Ellipse` with exactly ONE radius at 0 is a degenerate, zero-area face (`is_valid` reads
  `False` for `Ellipse(5, 0)` but (inconsistently) `True` for `Ellipse(0, 5)` — checked directly,
  neither is trustworthy) that reliably raises `RuntimeError: Failed to create valid loft` once it
  sits between two real stations in `bd.loft()` — reproduced directly. Because `max_width_mm` and
  `max_height_mm` (and their start/end tip values) are now independent params, a station where only
  ONE of the two half-extents rounds to zero is a real reachable state (unlike the old single-`dia`
  param, where both axes always collapsed together). `_section()` below therefore substitutes a
  `bd.Vertex` tip whenever EITHER half-extent collapses near zero, not only when both do — the
  degenerate zero-area ellipse case is never allowed to reach `bd.loft()`.
"""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems._loft_profiles import ease_at, taper_stations

_FRAGMENT = """\
## Subsystem: Lofted spindle
A general body-of-revolution primitive: a smooth loft between varying cross-sections along one axis,
then hollowed to a constant-wall shell. Thick in the middle, tapering at both ends — the
cross-industry shape family behind a bottle, a tool handle, a table/furniture spindle, a rocket body,
a shaft. NOT aerospace-specific. Cross-sections are ELLIPTICAL by default an ellipse whose width and
height happen to match, i.e. a circle — set max_height_mm different from max_width_mm for a
flattened, non-rotationally-symmetric cross-section (e.g. a real fuselage's flatter belly/wider-than-
tall shape); leave them equal (the default) for the original round spindle/bottle/shaft look.
- **length_mm** — overall length along the axis.
- **max_width_mm / max_height_mm** — cross-section size at the widest point (the plateau between the
  two tapers). Equal (the default) = circular; different = a flattened ellipse.
- **start_taper_mm / end_taper_mm** — length of the tapering region at each end. There is no
  separate "waist position" param — the widest point sits wherever start_taper_mm ends; push it
  forward by shortening start_taper_mm.
- **start_width_mm / start_height_mm, end_width_mm / end_height_mm** — tip cross-section size at each
  end. 0/0 tapers all the way to a true point (a cone/needle tip); a small positive value leaves a
  blunt, rounded cap instead.
- **wall_thickness_mm** — hollow shell wall thickness.

### Intent mapping
- "a bottle" / "a tool handle" → moderate start/end width+height (blunt ends) with a wide
  max_width_mm/max_height_mm plateau in the middle.
- "a rocket body" / "a pointed cone tip" → start_width_mm=start_height_mm=0 (or the end_ pair) for a
  true pointed tip.
- "fatter in the middle" → increase **max_width_mm**/**max_height_mm**; "move the widest point
  forward" → shorten **start_taper_mm** (the plateau begins sooner).
- "flattened" / "not perfectly round" / "wider than it is tall" → set **max_height_mm** below
  **max_width_mm** (or vice versa) instead of leaving them equal.
- "thicker wall" / "heavier" → increase **wall_thickness_mm** (watch the tips: the tightest end must
  keep at least the 0.8 mm min-wall floor of solid material once hollowed).\
"""

_MIN_WALL_MM = 0.8  # FDM min-wall floor, packages/ledger/apply.py::MIN_WALL_MM

_N_TAPER_STATIONS = 8  # stations sampled per taper zone for the outer loft — see module docstring
_N_VOLUME_STEPS = 200  # midpoint-rule disk-integration steps for _volume (pure python, cheap)
_POINT_EPS_MM = 1e-6  # a station half-extent at/below this is treated as a true point (Vertex tip)


def _width_at(x: float, p) -> float:
    """Half-width (>= 0) at axial position x in [0, length_mm], per the shared cosine-smoothstep
    taper (packages/subsystems/_loft_profiles.py) — the SAME formula backs both _build()'s (coarse)
    loft-station placement and _volume()'s (fine) numerical integration."""
    x_a = p.start_taper_mm
    x_b = p.length_mm - p.end_taper_mm
    return ease_at(x, x_a, x_b, p.length_mm,
                   p.start_width_mm / 2.0, p.max_width_mm / 2.0, p.end_width_mm / 2.0)


def _height_at(x: float, p) -> float:
    """Half-height (>= 0) at axial position x — independent schedule from _width_at(), same shared
    taper helper. Equal to _width_at() everywhere iff every width_mm param equals its height_mm
    counterpart (the default), which is exactly what keeps the default shape a true circle."""
    x_a = p.start_taper_mm
    x_b = p.length_mm - p.end_taper_mm
    return ease_at(x, x_a, x_b, p.length_mm,
                   p.start_height_mm / 2.0, p.max_height_mm / 2.0, p.end_height_mm / 2.0)


def _stations(p) -> list[tuple[float, float, float]]:
    """(x, width_half, height_half) triples along the axis for _build()'s outer loft — station
    x-positions come from the shared taper_stations() sampler (start-taper zone, plateau boundary,
    end-taper zone); pure python (no build123d) so _volume() can reuse the exact same schedule."""
    xs = taper_stations(p.length_mm, p.start_taper_mm, p.end_taper_mm, _N_TAPER_STATIONS)
    return [(x, _width_at(x, p), _height_at(x, p)) for x in xs]


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart

    stations = _stations(p)

    def _section(x: float, w_half: float, h_half: float):
        # Vertex tip whenever EITHER half-extent collapses to ~0 — NOT only when both do. See the
        # module docstring: a bd.Ellipse with exactly one radius at 0 is a degenerate zero-area face
        # that reliably raises `RuntimeError: Failed to create valid loft` inside bd.loft(); with
        # independent width/height tip params this one-sided-collapse state is genuinely reachable
        # (unlike the old single-diameter param, where both axes always hit zero together).
        if w_half <= _POINT_EPS_MM or h_half <= _POINT_EPS_MM:
            return bd.Vertex(x, 0, 0)
        # Rotation(0,90,0) maps local x_radius -> global Z half-extent, local y_radius -> global Y
        # half-extent (verified directly — see module docstring), so height goes first.
        return bd.Pos(x, 0, 0) * (bd.Rotation(0, 90, 0) * bd.Ellipse(h_half, w_half))

    outer = bd.loft([_section(x, w, h) for x, w, h in stations], ruled=False)

    # Hollow via an INNER loft + boolean subtract, NOT bd.offset(amount=-wall) — see module
    # docstring: with no openings, bd.offset doesn't hollow at all (blunt tips) and can raise or
    # segfault (pointed tips). Stations too close to a point tip (in EITHER dimension) for a wall to
    # fit are dropped, so the cavity loft caps itself short of the tip with a small flat disc rather
    # than reaching it — a wall of nonzero thickness physically cannot come to a zero-thickness
    # point anyway.
    inner_stations = [(x, w - p.wall_thickness_mm, h - p.wall_thickness_mm) for x, w, h in stations
                      if w - p.wall_thickness_mm > _POINT_EPS_MM and h - p.wall_thickness_mm > _POINT_EPS_MM]
    if len(inner_stations) >= 2:
        cavity = bd.loft([_section(x, w, h) for x, w, h in inner_stations], ruled=False)
        solid = outer - cavity
    else:
        # the body is too thin everywhere (relative to wall_thickness_mm) for any cavity to fit —
        # stays solid rather than risk a degenerate cavity loft. _check()'s min-wall invariant is
        # what should catch this upstream; this is a defensive fallback, not the expected path.
        solid = outer

    return TaggedPart(solid, {
        "spindle.body": {
            "kind": "solid", "length": p.length_mm,
            "max_width": p.max_width_mm, "max_height": p.max_height_mm,
        },
    })


def _volume(p) -> float:
    """Method-of-disks numerical integration over _width_at()/_height_at() — NOT a build123d call
    (the interactive plane is closed-form arithmetic only, no OCCT on that path, per CLAUDE.md).
    Each disk's area is the ellipse-area formula `pi * width_half * height_half` (reduces to the old
    `pi * r * r` exactly when width_half == height_half, i.e. the circular default). Outer volume
    minus an inner integral at (half-extent - wall_thickness_mm) per axis, clamped to 0 wherever that
    would go negative (a taper station narrower than the wall stays solid there, matching _build()'s
    inner-loft-station filtering).

    This is a disclosed APPROXIMATION, not fabricated: the real loft is a smooth B-spline through a
    handful of elliptical/circular stations, not a literal sweep of this cosine formula, so the true
    solid bulges past it between samples. Measured directly this session (on the circular case)
    against the real _build() output: ~3.7% over at this subsystem's default (gentle-taper) params,
    ~4.9% over at a blunt-both-ends (15mm tip) config, and ~9.1% over at the fully-pointed-both-ends
    (0mm tip) extreme — larger than the ~0.6% bulge figure this session's plan anticipated (that came
    from a milder profile), but the error stays roughly this same "several percent" order across the
    parameter space rather than blowing up at the pointed extreme, because _build()'s outer-loft and
    cavity-loft each overshoot their own closed-form targets by a good deal more (individually) and
    much of that cancels in the outer-minus-cavity subtraction. See test_lofted_spindle.py for the
    tolerance check (run at the default config).
    """
    dx = p.length_mm / _N_VOLUME_STEPS
    outer_vol = 0.0
    inner_vol = 0.0
    for i in range(_N_VOLUME_STEPS):
        xm = (i + 0.5) * dx
        w_half = _width_at(xm, p)
        h_half = _height_at(xm, p)
        outer_vol += math.pi * w_half * h_half * dx
        w_inner = max(0.0, w_half - p.wall_thickness_mm)
        h_inner = max(0.0, h_half - p.wall_thickness_mm)
        inner_vol += math.pi * w_inner * h_inner * dx
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
    if not (0.0 <= p.start_height_mm < p.max_height_mm):
        out.append(f"start_height {p.start_height_mm:.1f} mm must be >= 0 and < max_height {p.max_height_mm:.1f} mm")
    if not (0.0 <= p.end_width_mm < p.max_width_mm):
        out.append(f"end_width {p.end_width_mm:.1f} mm must be >= 0 and < max_width {p.max_width_mm:.1f} mm")
    if not (0.0 <= p.end_height_mm < p.max_height_mm):
        out.append(f"end_height {p.end_height_mm:.1f} mm must be >= 0 and < max_height {p.max_height_mm:.1f} mm")
    # Tightest across BOTH axes and BOTH tips, not just one dimension — a flattened tip is only as
    # strong as its thinnest direction.
    tightest_half = min(p.start_width_mm, p.end_width_mm, p.start_height_mm, p.end_height_mm) / 2.0
    if tightest_half - p.wall_thickness_mm < _MIN_WALL_MM:
        out.append(
            f"wall_thickness {p.wall_thickness_mm:.2f} mm leaves only "
            f"{tightest_half - p.wall_thickness_mm:.2f} mm of material at the tightest tip "
            f"(half-extent {tightest_half:.2f} mm) — need >= {_MIN_WALL_MM} mm"
        )
    return out


LOFTED_SPINDLE = register_subsystem(Subsystem(
    name="lofted_spindle",
    description="General body-of-revolution primitive — smooth loft between elliptical (or circular, "
                "the width==height default) cross-sections + hollow shell (bottle, handle, spindle, "
                "rocket body, fuselage, streamlined body)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("length_mm",         value=150.0, min=20.0, max=1000.0, unit="mm"),
        ParamSpec("max_width_mm",      value=40.0,  min=10.0, max=300.0,  unit="mm"),
        ParamSpec("max_height_mm",     value=40.0,  min=10.0, max=300.0,  unit="mm"),
        ParamSpec("start_taper_mm",    value=30.0,  min=0.0,  max=500.0,  unit="mm"),
        ParamSpec("end_taper_mm",      value=30.0,  min=0.0,  max=500.0,  unit="mm"),
        ParamSpec("start_width_mm",    value=20.0,  min=0.0,  max=300.0,  unit="mm"),
        ParamSpec("start_height_mm",   value=20.0,  min=0.0,  max=300.0,  unit="mm"),
        ParamSpec("end_width_mm",      value=20.0,  min=0.0,  max=300.0,  unit="mm"),
        ParamSpec("end_height_mm",     value=20.0,  min=0.0,  max=300.0,  unit="mm"),
        ParamSpec("wall_thickness_mm", value=2.0,   min=0.8,  max=15.0,   unit="mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # A lofted, variably-tapered hollow shell isn't a single-solid plate/bar shape — the validated
    # cantilever FS methodology (packages/truth_plane/solvers/fs.py) isn't a faithful re-use here.
    # FS honestly stays "unknown" for this part type, same call saddle_clamp.py made.
    fea_eligible=False,
))
