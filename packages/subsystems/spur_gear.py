"""Spur Gear -- REAL involute spur gear geometry (actual meshing teeth), via py_gearworks
(github.com/GarryBGoode/py_gearworks, build123d-native, pinned in constraints/kernel-linux.txt).

Unlike `gear_blank`/`pinion_blank`/`sprocket_blank` (a plain toothless cylindrical envelope --
"structural/mounting geometry only", their own docstrings say so explicitly), this subsystem builds
the actual involute tooth profile via `py_gearworks.SpurGear`, and is meant for a part whose real
function is to MESH with another gear (a gear train, not just a disc/hub). Do NOT touch/replace
gear_blank.py -- this is a new, additive subsystem for the case that actually needs real teeth.

### Cited formulas / standards (Inversion #1 -- physics/citation human wall)
- Pitch diameter: D = m * N (module m times number_of_teeth N) -- the defining relation of the metric
  module system, ANSI/AGMA 1012-G05 / ISO 21771 gear nomenclature. Used below ONLY to place the
  `kind="mesh"` interface (radial mate distance = pitch_radius_a + pitch_radius_b) and for the
  print-time-estimate volume approximation -- never as a strength/FS claim.
- Module preferred series: ISO 54:1996 (0.3, 0.4, 0.5, 0.8, 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10 mm,
  ...) -- module_mm's bounds below span this catalog's small-mechanism scale (matches gear_blank's/
  sprocket_blank's own ~10-130 mm diameter footprints).
- Standard pressure angles: 14.5 deg / 20 deg / 25 deg (AGMA/ISO 21771); 20 deg is the dominant modern
  standard (stronger tooth root than the legacy 14.5 deg profile) -- used as this catalog's default.
- Minimum tooth count before undercut (20 deg, full-depth, addendum_coefficient=1): Shigley's
  Mechanical Engineering Design (Budynas & Nisbett), N_min = 2*k / sin^2(phi) for a pinion meshing a
  rack (k=1 full-depth) = 2 / sin^2(20 deg) = 2 / 0.116978 = 17.10 -> ~17-18 teeth. ASSUMPTION stated
  explicitly: `tooth_count`'s floor below is set BELOW this (see bounds) because py_gearworks models
  undercut explicitly (`enable_undercut=True`, its own default) -- a lower tooth count still yields a
  real, geometrically valid (if undercut) tooth profile, not garbage geometry. This is disclosed as an
  ADVISORY fact in the fragment text below, not a hard invariant -- see the `_check` docstring for why.
- Face width rule of thumb: F in [3p, 5p] where p = circular pitch = pi * module (Shigley's Mechanical
  Engineering Design, spur-gear proportion guidance) -- face_width_mm's bounds below cover this typical
  band across the whole module_mm range.

### fea_eligible -- explicitly False, and WHY (do not flip this without a human FEA sign-off)
gear_blank/pinion_blank/sprocket_blank set `fea_eligible=True` because they ARE the validated
clamp-one-end/load-other-end cantilever shape (a plain solid cylinder) -- the SAME shape class as
round_post/longeron. A real involute gear is NOT that shape: the load path is tooth-root bending
stress concentration (a Lewis-form-factor / AGMA-stress problem), a genuinely different, harder
methodology nothing in `packages/truth_plane/solvers/` has validated. Copying `fea_eligible=True` from
gear_blank here would be exactly the mistake this file's own build instructions warned against --
factor_of_safety honestly stays "unknown" for this part until an FEA engineer signs off a real
tooth-root methodology.

### Duty-condition params (rpm, torque_nmm)
Plain, ordinary, user/LLM-settable ParamSpecs describing the gear's intended operating point -- NOT
derived/computed, and nothing in this codebase currently reads or solves against them (same posture as
any other stated-but-not-yet-solved duty condition elsewhere in this catalog). They exist so a
copilot/user can RECORD the operating point without this subsystem fabricating a safety scalar from it.
"""

from __future__ import annotations

import math

from packages.ledger.parameter import ParameterDef
from packages.subsystems import ParamSpec, Subsystem, register_subsystem
from packages.subsystems.base import InterfaceSpec, Namespace, cylinder_axis_mesh_interface

_FRAGMENT = """\
## Subsystem: Spur Gear
A real involute spur gear -- actual meshing teeth (py_gearworks), not a toothless blank. Use this when
the part must actually MESH with another gear in a gear train; use `gear_blank` for a disc/hub that
just needs the right envelope (mount holes, a shaft bore) with no real teeth.
- **module_mm** -- tooth size (pitch diameter = module_mm x tooth_count). ISO 54 preferred values:
  0.3, 0.4, 0.5, 0.8, 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10 mm.
- **tooth_count** -- number of teeth. Below ~17-18 teeth at the default 20 deg pressure angle the tooth
  root shows undercut (Shigley's minimum-teeth formula) -- py_gearworks still generates a real, valid
  (if undercut) profile, this is disclosed, not blocked.
- **pressure_angle_deg** -- 14.5 / 20 / 25 deg are the AGMA/ISO standard values; 20 deg is the modern
  default. Must match the mating gear's pressure angle for correct meshing.
- **face_width_mm** -- axial tooth length. Typical rule of thumb: 3-5x the circular pitch (pi x module).
- **rpm** / **torque_nmm** -- stated operating point (duty condition), NOT solved against by anything
  yet -- record only, never treat as a safety input.

### Intent mapping
- "gear" / "pinion" / "spur gear" / "meshing gear" -> this part (real teeth). A plain "gear blank"/
  "toothless disc" request -> `gear_blank` instead.
- "finer teeth" / "smaller teeth" -> decrease **module_mm**; "coarser/bigger teeth" -> increase it.
- "more teeth" (same module -> bigger gear, same pitch) -> increase **tooth_count**.
- "wider gear" / "thicker teeth (axially)" -> increase **face_width_mm**.
- factor_of_safety for this part is always "unknown" -- no FEA methodology exists yet for tooth-root
  stress (see `packages/subsystems/spur_gear.py`'s module docstring). Never state a numeric FS for it.\
"""


def _build(p):
    from py_gearworks import SpurGear  # lazy: build123d/py_gearworks live only in the Linux kernel image
    from packages.truth_plane.regen.templated import TaggedPart

    n_teeth = int(round(p.tooth_count))
    gear = SpurGear(
        number_of_teeth=n_teeth,
        module=p.module_mm,
        height=p.face_width_mm,
        pressure_angle=math.radians(p.pressure_angle_deg),
        # z_anchor=0.5 centers the face width on local Z (spans -face_width/2 .. +face_width/2),
        # matching the centered-cylinder convention cylinder_axis_mesh_interface/
        # cylinder_end_interfaces assume for this shape family (round_post et al.) -- py_gearworks'
        # OWN default (z_anchor=0) instead anchors the bottom face at local Z=0, which would NOT match.
        z_anchor=0.5,
    )
    part = gear.build_part()
    pitch_dia_mm = p.module_mm * p.tooth_count  # D = m * N -- see module docstring citation
    return TaggedPart(part, {
        "gear.body": {
            "kind": "solid",
            "module_mm": p.module_mm,
            "teeth": n_teeth,
            "pressure_angle_deg": p.pressure_angle_deg,
            "face_width_mm": p.face_width_mm,
            "pitch_dia_mm": pitch_dia_mm,
        }
    })


def _volume(p) -> float:
    # Approximation, NOT the real toothed volume: a cylinder at the PITCH diameter. Disclosed
    # simplification (same posture as knurled_nut's "approximated, no knurl grooves") -- for a
    # standard-proportion involute gear, the addendum material added above the pitch line and the
    # dedendum material removed by the tooth gaps below it roughly offset, which is why a pitch-circle
    # cylinder is the conventional first-pass mass estimate for a gear blank. Used for print-time/mass
    # telemetry only -- never a structural claim (see fea_eligible=False above).
    pitch_radius_mm = (p.module_mm * p.tooth_count) / 2.0
    return math.pi * pitch_radius_mm ** 2 * p.face_width_mm


def _check(p) -> list[str]:
    # Mirrors gear_blank's/pinion_blank's/sprocket_blank's own 0.8 mm min-wall floor, applied to this
    # part's axial thin dimension (face_width_mm plays the same role their height_mm does). Undercut
    # (see module docstring) is NOT checked here: py_gearworks produces a real, valid tooth profile
    # even when undercut, so it is disclosed as advisory guidance in the fragment text, not a hard
    # invariant -- `check_invariants` reasons are a HARD CONFLICT/reject in packages/ledger/apply.py,
    # and undercut is a legitimate (if suboptimal) design choice, not a broken one.
    if p.face_width_mm < 0.8:
        return [f"face_width {p.face_width_mm:.2f} mm < min wall 0.8 mm"]
    return []


# 2026-08-04 -- cylinder_axis_mesh_interface (packages/subsystems/base.py) expects a single STORED
# diameter ParamSpec name (it reads `getattr(p, dia_param)` off the resolved Namespace). This gear's
# pitch diameter is D = module_mm * tooth_count -- DERIVED from TWO independent params, not a param of
# its own. Storing it as a third, independently-settable ParamSpec would let it drift out of sync with
# module_mm/tooth_count -- exactly the fabricated/duplicated-authoritative-value pattern CLAUDE.md's
# Inversion #1 forbids. So: reuse the helper's own origin/normal/radius arithmetic (no parallel helper
# written) by handing it a tiny one-field Namespace holding the pitch diameter computed FRESH on every
# call and never written back to the ledger -- read-time/display-only, same posture as every other new
# derived value this session.
_MESH_PROTO = cylinder_axis_mesh_interface("pitch_dia_mm")


def _mesh_frame(p: "Namespace"):
    pitch_dia_mm = p.module_mm * p.tooth_count  # D = m * N -- see module docstring citation
    aug = Namespace({"pitch_dia_mm": ParameterDef(value=pitch_dia_mm, unit="mm", bounds=(0.0, 1.0e6))})
    return _MESH_PROTO.frame(aug)


_GEAR_MESH_INTERFACE = InterfaceSpec(
    name=_MESH_PROTO.name, kind=_MESH_PROTO.kind, frame=_mesh_frame, keepout_mm=_MESH_PROTO.keepout_mm,
)


SPUR_GEAR = register_subsystem(Subsystem(
    name="spur_gear",
    description="Real involute spur gear (py_gearworks) -- actual meshing teeth, not a toothless blank",
    fragment=_FRAGMENT,
    disciplines=("structures", "manufacturing", "thermal"),
    params=[
        # ISO 54 preferred module series spans roughly 0.3-10 mm for small-instrument/hobby-mechanism
        # gears; bounded to this catalog's scale (gear_blank/sprocket_blank top out ~120-130 mm dia).
        ParamSpec("module_mm", value=1.5, min=0.3, max=6.0, unit="mm"),
        # Shigley's undercut floor (20 deg PA) is ~17-18 teeth; the lower bound here deliberately goes
        # below that (py_gearworks models undercut explicitly, see module docstring) for user
        # flexibility. Upper bound matches this catalog's largest cylinder-family footprints.
        ParamSpec("tooth_count", value=20.0, min=6.0, max=150.0, unit="count"),
        # AGMA/ISO standard pressure angles are 14.5 / 20 / 25 deg; 20 deg is the modern default.
        ParamSpec("pressure_angle_deg", value=20.0, min=14.5, max=25.0, unit="deg"),
        # Shigley's rule of thumb: F in [3p, 5p], p = pi * module -- at module 0.3..6 mm that's roughly
        # 2.8..94 mm; bounded a bit past that top end for user flexibility.
        ParamSpec("face_width_mm", value=8.0, min=2.0, max=100.0, unit="mm"),
        # Duty-condition inputs (see module docstring) -- plain stated values, not derived/solved.
        ParamSpec("rpm", value=3000.0, min=0.0, max=20000.0, unit="rpm"),
        ParamSpec("torque_nmm", value=500.0, min=0.0, max=50000.0, unit="N*mm"),
    ],
    build=_build,
    volume=_volume,
    invariants=_check,
    # False, deliberately -- see the module docstring's "fea_eligible" section. A real gear's tooth-root
    # stress concentration is NOT the validated plain-cylinder/cantilever methodology gear_blank opts
    # into; no FEA engineer has signed off a tooth-root methodology, so factor_of_safety stays
    # "unknown" for this part, never a fabricated green light (Inversion #1).
    fea_eligible=False,
    # Driven by the gear's own pitch diameter (module_mm x tooth_count) -- see the derivation note
    # above _MESH_PROTO. Only the mesh interface is declared here (no axial mount interfaces) --
    # matching exactly what was asked; a bore/shaft-mount interface is a separate, un-requested feature.
    interfaces=[_GEAR_MESH_INTERFACE],
))
