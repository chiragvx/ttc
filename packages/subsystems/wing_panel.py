"""Wing panel — a HALF-span tapered NACA airfoil panel: root (max chord) at the INNER end where it
bolts onto a body, tapering in ONE clean line to a single OUTER tip. `naca_wing`'s single-sided
sibling, built for exactly the job `naca_wing` is WRONG for.

WHY THIS EXISTS (found live, 2026-07-19, from a rendered BWB-plus-wings screenshot): `naca_wing` is a
FULL-span, SYMMETRIC wing — its max chord sits at its own CENTRE and it tapers to a tip at BOTH ends
(see `naca_wing.py`: `_stations = [-half, 0, half]`, max chord at `dist_from_center == 0`). That's
correct when it IS the whole wing (spanning the aircraft, passing through/over the body, the way
`winged_fuselage` uses it). But bolting one onto EACH SIDE of a body as a side panel gives a
lens/football shape — thin at the body join, THICK in the middle of the panel, thin again at the tip —
because the max chord is stranded in the middle of the panel instead of at the root. No placement can
fix that (you cannot move a centre-max taper to an edge-max one). A side panel needs its max chord at
the INNER (root) end and a single monotonic taper outward — which is exactly this subsystem.

SIDE (left/right) is baked into the geometry, not a rotation (deliberate — the recurring live pain has
been the copilot mis-rotating parts; a rotation that mirrors a swept panel also flips its sweep from
aft to forward). `side_sign` picks the build direction: the panel is built with its root at local
x=0 and its tip at `+span` (right) or `-span` (left), while sweep still shifts every section AFT (+Y)
and dihedral still shifts it UP (+Z) REGARDLESS of side — so a left and a right panel with the same
params form a correct symmetric pair (both sweep aft, both dihedral up) with ZERO rotation at the
placement site. `side_sign` is read as a sign only (`>= 0` -> right, `< 0` -> left) via a full-length
`copysign`, so there is no degenerate zero-length-panel value in its range and it needs no invariant —
a slider dragged across 0 simply flips the panel to the other side, always a valid solid.

ATTACHING IT (the placement the BWB recipe uses — see packages/agents/prompt_builder.py): because the
root is at the panel's OWN local origin (NOT offset by half a span, the way `naca_wing`'s centre is),
placing the panel INSTANCE at a body's tip station puts the root exactly on the body edge — no
"+ span/2" fudge. For a body whose own sweep/dihedral has already shifted its tip to
`(±body.span/2, (body.span/2)·tan(body.sweep), (body.span/2)·tan(body.dihedral))`, dropping the panel
there with `root_chord = body.tip_chord`, `thickness_pct = body.tip_thickness_pct`, and the SAME
`sweep_deg`/`dihedral_deg` continues the body's own outline seamlessly outward.

Same disclosed-approximation stance as `naca_wing` (which this file's loft/area math mirrors exactly):
a real periodic-B-spline NACA section vs. the analytic area integral, `ruled=True` straight-line
taper between the two real stations — measured a few percent at typical params, regression-tested."""

from __future__ import annotations

import math

from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems._naca_airfoil import (
    naca4_half_thickness,
    naca4_profile_points,
    sweep_dihedral_offset,
)

_FRAGMENT = """\
## Subsystem: Wing panel
A HALF-span tapered wing panel (real NACA 4-digit airfoil section) — root (max chord) at the INNER
end where it attaches to a body, tapering in ONE clean line to a single OUTER tip. This is the part
you bolt onto EACH SIDE of a fuselage/centerbody. NOT `naca_wing` (which is a full-span symmetric wing,
max chord in the MIDDLE, tapering to two tips — that one is the WHOLE wing through the body, and used
as a side panel it makes a wrong lens/football shape). SOLID.
- **span_mm** — the panel's own root-to-tip length (the EXPOSED wing length on one side; NOT the whole
  aircraft span).
- **root_chord_mm** — chord at the INNER (root) end. Set this to the body's own tip chord for a
  seamless join.
- **tip_chord_mm** — chord at the OUTER tip (must be <= root_chord_mm; a panel tapers root-to-tip).
- **thickness_pct** — max thickness as % of local chord, held constant (12.0 = NACA0012). Match the
  body's own tip thickness_pct for a seamless join.
- **sweep_deg** — aft sweep; every section shifts aft proportional to distance from the root. Match
  the body's sweep to continue the same leading-edge line.
- **dihedral_deg** — upward rise, same convention.
- **side_sign** — +1 builds the panel to the RIGHT (+X), -1 to the LEFT (-X). Sweep stays aft and
  dihedral stays up on BOTH sides, so a matched +1 and -1 pair is a correct symmetric wing set with no
  rotation needed. Set it explicitly (+1 or -1); do not leave both panels on the same side.

### Intent mapping
- "a wing on each side of the body" / "wing panels" / "outer wings continuing from the body" -> two
  `wing_panel`s (side_sign +1 and -1), NOT `naca_wing`.
- "a tapered wing panel" -> tip_chord_mm below root_chord_mm.
- "swept" -> increase sweep_deg (both panels the same value; side_sign handles the mirroring).\
"""

_MIN_WALL_MM = 0.8  # FDM min-wall floor, packages/ledger/apply.py::MIN_WALL_MM

_N_AIRFOIL_PTS_PER_SIDE = 20
_N_VOLUME_STEPS = 200
_AREA_INTEGRATION_STEPS = 50
_EPS_MM = 1e-9
_POINT_EPS_MM = 1e-6


def _chord_at(dist_from_root: float, p) -> float:
    """Local chord at `dist_from_root` (>= 0, measured from the root at the inner end toward the tip) —
    a PLAIN LINEAR taper from `root_chord_mm` (at `dist == 0`) to `tip_chord_mm` (at `dist == span_mm`),
    the same straight-edge taper `naca_wing._chord_at` uses (a real tapered wing's edges are straight
    lines). Unlike `naca_wing`, the max is at ONE END (the root), not the centre — that is the whole
    point of this subsystem."""
    if p.span_mm <= _EPS_MM:
        return p.root_chord_mm
    t = min(1.0, dist_from_root / p.span_mm)
    return p.root_chord_mm + (p.tip_chord_mm - p.root_chord_mm) * t


def _side(p) -> float:
    """+1.0 (right, tip at +span) or -1.0 (left, tip at -span) — read as a SIGN only, so any nonzero
    `side_sign` picks a side and there is no degenerate zero-length panel in the param's range."""
    return 1.0 if p.side_sign >= 0.0 else -1.0


def _stations(p) -> list[float]:
    """Loft-axis (X) sample positions: root at local x=0, tip at `side * span_mm`. Only two stations
    are needed — the taper is exactly linear (see `_chord_at`), so a straight `ruled=True` loft between
    the root and tip profiles reproduces it exactly, nothing to approximate in between."""
    return [0.0, _side(p) * p.span_mm]


def _section_points(x: float, p) -> list[tuple[float, float, float]]:
    dist = abs(x)
    chord = _chord_at(dist, p)
    y_offset, z_offset = sweep_dihedral_offset(dist, p.sweep_deg, p.dihedral_deg)
    return naca4_profile_points(x, chord, p.thickness_pct, _N_AIRFOIL_PTS_PER_SIDE,
                                y_offset=y_offset, z_offset=z_offset)


def _build(p):
    import build123d as bd
    from packages.truth_plane.regen.templated import TaggedPart

    def _section(x: float):
        dist = abs(x)
        chord = _chord_at(dist, p)
        if chord <= _POINT_EPS_MM:
            y_offset, z_offset = sweep_dihedral_offset(dist, p.sweep_deg, p.dihedral_deg)
            return bd.Vertex(x, y_offset, z_offset)
        pts = _section_points(x, p)
        return bd.Face(bd.Wire([bd.Spline(*pts, periodic=True)]))

    # ruled=True: straight-line elements between root and tip profiles — a sharp real wing taper, the
    # same choice naca_wing makes (see its module docstring), NOT the smooth-blend ruled=False the
    # body-of-revolution subsystems use.
    solid = bd.loft([_section(x) for x in _stations(p)], ruled=True)

    return TaggedPart(solid, {
        "wing_panel.body": {
            "kind": "solid", "span": p.span_mm,
            "root_chord": p.root_chord_mm, "tip_chord": p.tip_chord_mm,
            "thickness_pct": p.thickness_pct, "side": _side(p),
            "sweep_deg": p.sweep_deg, "dihedral_deg": p.dihedral_deg,
        },
    })


def _airfoil_area(chord: float, thickness_pct: float, n: int = _AREA_INTEGRATION_STEPS) -> float:
    """Cross-sectional area of one closed NACA 4-digit symmetric profile — identical technique to
    `naca_wing._airfoil_area` (midpoint integral of `2*naca4_half_thickness` over `[0, chord]`)."""
    if chord <= _EPS_MM:
        return 0.0
    dx = chord / n
    area = 0.0
    for i in range(n):
        xm = (i + 0.5) * dx
        area += 2.0 * naca4_half_thickness(xm, chord, thickness_pct) * dx
    return area


def _volume(p) -> float:
    """Method-of-disks integration along the span over `_chord_at`/`_airfoil_area` — NOT a build123d
    call (interactive plane stays closed-form-only per CLAUDE.md). Sweep/dihedral shift each section's
    Y/Z but not its area, so they don't enter the integral. Disclosed approximation, same order as
    `naca_wing`'s own — see module docstring."""
    dx = p.span_mm / _N_VOLUME_STEPS
    vol = 0.0
    for i in range(_N_VOLUME_STEPS):
        dist = (i + 0.5) * dx
        vol += _airfoil_area(_chord_at(dist, p), p.thickness_pct) * dx
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
    # A panel tapers ROOT->TIP, never the reverse — same structural sanity (and same aggregate-integral
    # blind spot) as naca_wing's own reversed-taper check: the root carries the highest bending load
    # and needs the most material, and wing area/MAC are algebraically identical whether the two
    # endpoint chords are swapped, so this MUST be a pointwise check.
    if p.root_chord_mm < p.tip_chord_mm:
        out.append(
            f"root_chord_mm {p.root_chord_mm:.1f} mm is smaller than tip_chord_mm {p.tip_chord_mm:.1f} "
            f"mm -- a wing panel must taper root-to-tip (or stay untapered), never the reverse"
        )
    # Tightest thickness is at the tip (smaller chord). Max thickness IS thickness_pct% of the local
    # chord by the NACA 4-digit definition — reuse that exact relationship, not a separate estimate.
    if p.tip_chord_mm > 0.0 and p.thickness_pct > 0.0:
        tip_thickness = p.tip_chord_mm * p.thickness_pct / 100.0
        if tip_thickness < _MIN_WALL_MM:
            out.append(
                f"thickness_pct {p.thickness_pct:.1f}% of tip_chord_mm {p.tip_chord_mm:.1f} mm gives "
                f"only {tip_thickness:.2f} mm max thickness at the tip -- need >= {_MIN_WALL_MM} mm"
            )
    # side_sign intentionally has NO invariant — any nonzero value picks a side (see _side); a value of
    # exactly 0.0 still resolves to +1 (right) via the `>= 0` rule, so even that is a valid solid.
    return out


WING_PANEL = register_subsystem(Subsystem(
    name="wing_panel",
    description="Half-span tapered NACA wing panel -- root (max chord) at the inner/body end tapering "
                "to a single outer tip; side_sign picks left/right. The part you bolt onto each side "
                "of a body (unlike naca_wing, which is a full-span symmetric wing through the body)",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        ParamSpec("span_mm",       value=250.0, min=50.0,  max=2000.0, unit="mm"),
        ParamSpec("root_chord_mm", value=120.0, min=20.0,  max=600.0,  unit="mm"),
        ParamSpec("tip_chord_mm",  value=60.0,  min=10.0,  max=600.0,  unit="mm"),
        ParamSpec("thickness_pct", value=12.0,  min=6.0,   max=21.0,   unit="pct"),
        ParamSpec("sweep_deg",     value=15.0,  min=-30.0, max=45.0,   unit="deg"),
        ParamSpec("dihedral_deg",  value=2.0,   min=-10.0, max=20.0,   unit="deg"),
        ParamSpec("side_sign",     value=1.0,   min=-1.0,  max=1.0,    unit="sign"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # A lofted airfoil panel isn't a single-solid plate/bar the validated cantilever FS methodology
    # faithfully covers -- FS stays "unknown", same stance as naca_wing.
    fea_eligible=False,
    # A lifting surface sets part of the vehicle's outer mold line, same as naca_wing -> airframe-
    # defining (see packages/agents/prompt_builder.py's airframe-first pacing).
    is_airframe_defining=True,
))
