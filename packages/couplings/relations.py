"""The relation catalog (Phase 2, 2026-07-19) — the versioned, deterministic, TESTED library of
physical relationships the coupling graph runs, and the ONLY place coupling math lives.

THE ONE NON-NEGOTIABLE RULE (Inversion #1): the LLM WIRES relations by name, it never AUTHORS them. A
relation is a registered pure function `f(**inputs) -> output`, exactly like a subsystem's geometry
`build` is a registered generator the LLM invokes but never writes. A coupling naming a relation NOT in
this registry yields `"unknown"` (packages/couplings/resolve.py) — which blocks the green light, never
fabricates one. Growing the catalog is deliberate, one grounded relation at a time.

SCOPE v1, deliberately tiny (ENGINEERING_GRAPH_PLAN.md P2): four trivial, unarguable, closed-form
relations — enough to make the pump-style propagation real end-to-end, nothing hard. The nasty ones
(FATIGUE especially — the mode that actually cracked the pump's crank, needing S-N curves and
stress-concentration factors) are a HUMAN WALL: not here, and a coupling that needs one gets "unknown",
not a static number wearing a fatigue label (ENGINEERING_GRAPH_ARCHITECTURE.md §0.1).

2026-07-31: four more handbook leaf relations added (stress/deflection/spring/torsion) — same rules:
every one is a textbook closed-form, verified against a hand-computed value in tests/couplings/, and
still no chaining (a relation's inputs are still only literals or a single part param, never another
relation's output).

2026-08-04: two gear-ratio kinematic relations added (`gear_ratio_speed_out`, `gear_ratio_torque_out`)
— a simple two-gear (or belt/chain) mesh's output speed and output torque from tooth counts. Both are
explicitly IDEAL/LOSSLESS in their own description string (no fabricated real-world efficiency number
is asserted anywhere — see the description text itself). See
`test_gear_ratio_torque_out_unit_matches_other_torque_nmm_relations_in_registry` in tests/couplings/
for the unit-consistency check against the pre-existing torque_nmm-typed relations, continuing the
2026-08-03 1000x-mismatch-fix discipline below.

2026-08-03 — TWO changes, both a human-wall physics review:

1. UNIT-MISMATCH FIX (was dormant only because chaining doesn't exist yet): `torque_from_force_radius`
   used to emit `torque_nm` (N*m) while `shear_stress_from_torque_radius` consumes `torque_nmm` (N*mm)
   — the only two torque quantities in the whole registry, 1000x apart. Standardized on N*mm (matching
   `moment_nmm`'s existing convention in this same registry): `torque_from_force_radius` now emits
   `torque_nmm`. **BREAKING CHANGE** for any coupling already wired against the old `torque_nm`/N*m
   output in a live ledger — the numeric value for the SAME physical torque is now 1000x LARGER (N*mm
   vs N*m), not a relabeling; any such wiring must be re-verified, not silently trusted. Pinned by
   `test_torque_output_unit_matches_shear_stress_input_unit_no_1000x_mismatch` in tests/couplings/.
2. Eight new relations closing the highest-value gaps for the truth-plane's CANTILEVER FS methodology
   (the only one it implements): cantilever bending (point load + distributed load), section
   properties (rectangular/circular second moment of area, circular polar second moment of area —
   without these an LLM caller would have to hand-supply them as bare literals, reopening exactly the
   "LLM originates the physical number" path this registry exists to close), Euler buckling (one
   explicitly-stated end-fixity convention), and bolted-joint preload-from-torque + bolt shear. Every
   one cites its handbook source and states its boundary-condition assumption in its own description,
   exactly like `bending_from_distributed_load` already does. Fatigue/S-N/stress-concentration remain
   an explicit, untouched human wall — see `test_no_fatigue_or_stress_concentration_relations_registered`.

Units are explicit in every quantity NAME (`_n`, `_mm`, `_pa`, `_g`, `_nmm`) so a mismatch is visible,
not silent. Every relation is verified against a hand-computed value in tests/couplings/.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

_G_MPS2 = 9.80665  # standard gravity, for g-load -> acceleration


@dataclass(frozen=True)
class Relation:
    """One registered physical relationship. `inputs` are the named input quantities (name -> unit
    label, for display/validation); `output` is (name, unit); `fn` is the pure evaluator taking the
    inputs as kwargs by their names and returning the output scalar. Deterministic, no I/O."""

    name: str
    description: str
    inputs: dict[str, str]          # quantity_name -> unit label
    output: tuple[str, str]         # (quantity_name, unit label)
    fn: Callable[..., float]

    def evaluate(self, values: dict[str, float]) -> float:
        return self.fn(**{k: values[k] for k in self.inputs})


RELATION_REGISTRY: dict[str, Relation] = {}


def register_relation(rel: Relation) -> Relation:
    if rel.name in RELATION_REGISTRY:
        raise ValueError(f"relation {rel.name!r} already registered")
    RELATION_REGISTRY[rel.name] = rel
    return rel


def get_relation(name: str) -> Relation:
    if name not in RELATION_REGISTRY:
        raise KeyError(f"unknown relation {name!r}. Registered: {sorted(RELATION_REGISTRY)}")
    return RELATION_REGISTRY[name]


# --- the tiny v1 catalog -------------------------------------------------------------------------

register_relation(Relation(
    name="force_from_mass_accel",
    description="Inertial load: force = mass x acceleration (a payload/component under a g-load).",
    inputs={"mass_g": "g", "accel_g": "g-load"},
    output=("force_n", "N"),
    fn=lambda mass_g, accel_g: (mass_g / 1000.0) * (accel_g * _G_MPS2),
))

register_relation(Relation(
    name="force_from_pressure_area",
    description="Pressure load: force = pressure x area (the pump's chamber pressure on a piston/crank "
                "pin — the coupling that cracked the crankshaft when the casing diameter grew).",
    inputs={"pressure_pa": "Pa", "area_mm2": "mm^2"},
    output=("force_n", "N"),
    fn=lambda pressure_pa, area_mm2: pressure_pa * (area_mm2 * 1e-6),
))

register_relation(Relation(
    name="torque_from_force_radius",
    description="Torque = force x radius (a force at a crank throw / lever arm). Output is torque_nmm "
                "(N*mm), NOT N*m (2026-08-03 fix: this relation previously emitted torque_nm/N*m, a "
                "value 1000x too small to ever legitimately feed shear_stress_from_torque_radius's "
                "torque_nmm input — the only two torque quantities in this registry, standardized here "
                "on N*mm to match moment_nmm's existing convention in this same catalog). Because force "
                "is in N and radius in mm, N*mm falls out directly with no conversion factor.",
    inputs={"force_n": "N", "radius_mm": "mm"},
    output=("torque_nmm", "N*mm"),
    fn=lambda force_n, radius_mm: force_n * radius_mm,
))

register_relation(Relation(
    name="bending_from_distributed_load",
    description="Peak bending moment of a SIMPLY-SUPPORTED beam under a uniformly distributed total "
                "load W over span L: M = W*L/8. NOTE this is the pinned-both-ends case; a root-fixed "
                "CANTILEVER (e.g. a wing spar carrying lift, fixed at the fuselage) is a DIFFERENT "
                "formula (M = W*L/2) that is not in the v1 catalog yet — do not use this relation for "
                "a cantilever.",
    inputs={"total_load_n": "N", "span_mm": "mm"},
    output=("moment_nmm", "N*mm"),
    fn=lambda total_load_n, span_mm: total_load_n * span_mm / 8.0,
))

# --- 2026-07-31 additions: four more handbook leaf relations, same rules apply ------------------

register_relation(Relation(
    name="stress_from_force_area",
    description="Nominal (average) normal stress over a cross-section: stress = force / area, "
                "uniformly distributed (no stress-concentration factor — that is a separate, "
                "geometry-specific correction, not part of this relation). Because force is expressed "
                "in N and area in mm^2, the ratio is already in N/mm^2 == MPa with no conversion "
                "factor needed.",
    inputs={"force_n": "N", "area_mm2": "mm^2"},
    output=("stress_mpa", "MPa"),
    fn=lambda force_n, area_mm2: force_n / area_mm2,
))

register_relation(Relation(
    name="deflection_of_cantilever_beam",
    description="Tip deflection of a CANTILEVER beam (fixed at one end, free at the other) under a "
                "point load P applied AT THE FREE END: delta = P*L^3/(3*E*I) (Roark's Formulas for "
                "Stress and Strain / Shigley Table A-9, case 1). NOTE this is the point-load-at-the-"
                "tip case; a uniformly DISTRIBUTED load along a cantilever is a DIFFERENT formula "
                "(delta = w*L^4/(8*E*I)), not this relation. Using N, mm, MPa (== N/mm^2), and mm^4 "
                "keeps the result in mm with no conversion factor needed.",
    inputs={"force_n": "N", "length_mm": "mm", "modulus_mpa": "MPa", "moment_of_inertia_mm4": "mm^4"},
    output=("deflection_mm", "mm"),
    fn=lambda force_n, length_mm, modulus_mpa, moment_of_inertia_mm4: (
        (force_n * length_mm ** 3) / (3.0 * modulus_mpa * moment_of_inertia_mm4)
    ),
))

register_relation(Relation(
    name="spring_force_from_rate_deflection",
    description="Hooke's Law for a linear spring: force = spring rate x deflection (the force needed "
                "to hold/produce a given deflection on a part whose rate is known).",
    inputs={"spring_rate_n_per_mm": "N/mm", "deflection_mm": "mm"},
    output=("force_n", "N"),
    fn=lambda spring_rate_n_per_mm, deflection_mm: spring_rate_n_per_mm * deflection_mm,
))

register_relation(Relation(
    name="shear_stress_from_torque_radius",
    description="Torsional shear stress at radius r in a CIRCULAR (round) shaft: tau = T*r/J, where J "
                "is the polar second moment of area of the cross-section (Shigley eq. 3-37, the "
                "standard torsion formula). Valid for circular cross-sections only — a non-circular "
                "shaft needs a shape-dependent torsion correction, not this relation. Using N*mm, mm, "
                "and mm^4 keeps the result in N/mm^2 == MPa with no conversion factor needed.",
    inputs={"torque_nmm": "N*mm", "radius_mm": "mm", "polar_moment_mm4": "mm^4"},
    output=("shear_stress_mpa", "MPa"),
    fn=lambda torque_nmm, radius_mm, polar_moment_mm4: (torque_nmm * radius_mm) / polar_moment_mm4,
))

# --- 2026-08-03 additions: cantilever bending, section properties, Euler buckling, bolted joint -----
# GAP being closed: the truth-plane solver's ONLY factor-of-safety methodology is CANTILEVER
# (packages/truth_plane/solvers/cases.py Cantilever), but the only beam-moment relation above
# (bending_from_distributed_load) is SIMPLY-SUPPORTED. The two relations below are the CANTILEVER
# case, and both deliberately reuse the "moment_nmm" output-quantity name that
# bending_from_distributed_load already uses, and that packages/transport/app.py's
# `_iter_coarse_cantilever_fs` already looks for (`r.output_quantity == "moment_nmm"`) — so both
# become consumable by the existing FS estimator the moment they're wired, with no downstream change.

register_relation(Relation(
    name="bending_from_cantilever_point_load",
    description="Maximum bending moment of a CANTILEVER beam (fixed at the root, free at the other "
                "end) under a POINT LOAD applied AT THE FREE END/tip: M = F*L, the moment occurring at "
                "the fixed root (Euler-Bernoulli cantilever beam theory; Shigley Table A-9 case 1 / "
                "Roark's Formulas for Stress and Strain). This is the tip-point-load case — a "
                "uniformly DISTRIBUTED load along the span is a DIFFERENT relation "
                "(bending_from_cantilever_distributed_load, M=W*L/2), and a beam pinned at BOTH ends "
                "is a different relation still (bending_from_distributed_load, M=W*L/8) — do not use "
                "this one for either of those cases.",
    inputs={"force_n": "N", "length_mm": "mm"},
    output=("moment_nmm", "N*mm"),
    fn=lambda force_n, length_mm: force_n * length_mm,
))

register_relation(Relation(
    name="bending_from_cantilever_distributed_load",
    description="Maximum bending moment of a CANTILEVER beam (fixed at the root, free at the other "
                "end) under a UNIFORMLY DISTRIBUTED load of total magnitude W spread over the full "
                "span L: M = W*L/2, the moment occurring at the fixed root (Euler-Bernoulli cantilever "
                "beam theory; Shigley Table A-9 case 3 / Roark's Formulas for Stress and Strain). This "
                "is the distributed-load case — a POINT load at the tip is a DIFFERENT relation "
                "(bending_from_cantilever_point_load, M=F*L), and a beam pinned at BOTH ends is a "
                "different relation still (bending_from_distributed_load, M=W*L/8) — do not use this "
                "one for either of those cases.",
    inputs={"total_load_n": "N", "span_mm": "mm"},
    output=("moment_nmm", "N*mm"),
    fn=lambda total_load_n, span_mm: total_load_n * span_mm / 2.0,
))

register_relation(Relation(
    name="second_moment_of_area_rectangular",
    description="Second moment of area (area moment of inertia) of a SOLID RECTANGULAR cross-section "
                "about the centroidal bending axis: I = b*h^3/12, the standard rectangular-section "
                "formula (e.g. Shigley Table A-18 / Beer & Johnston, Mechanics of Materials). "
                "`height_mm` is the section dimension PARALLEL to the direction of bending (the "
                "beam's depth in the plane of the applied load); `width_mm` is perpendicular to it. "
                "Solid rectangle only — a tube/channel/I-beam section needs a different, "
                "shape-specific formula, not this one.",
    inputs={"width_mm": "mm", "height_mm": "mm"},
    output=("moment_of_inertia_mm4", "mm^4"),
    fn=lambda width_mm, height_mm: width_mm * height_mm ** 3 / 12.0,
))

register_relation(Relation(
    name="second_moment_of_area_circular",
    description="Second moment of area (area moment of inertia) of a SOLID CIRCULAR cross-section "
                "about a diametral (centroidal) axis: I = pi*d^4/64, the standard circular-section "
                "formula (e.g. Shigley Table A-18 / Beer & Johnston, Mechanics of Materials). Solid "
                "round bar only — a hollow (tube) circular section needs I = pi*(d_o^4-d_i^4)/64, a "
                "different relation, not this one.",
    inputs={"dia_mm": "mm"},
    output=("moment_of_inertia_mm4", "mm^4"),
    fn=lambda dia_mm: math.pi * dia_mm ** 4 / 64.0,
))

register_relation(Relation(
    name="polar_second_moment_of_area_circular",
    description="Polar second moment of area of a SOLID CIRCULAR cross-section, i.e. the `J` consumed "
                "by shear_stress_from_torque_radius's polar_moment_mm4 input: J = pi*d^4/32, the "
                "standard circular-shaft torsion formula (Shigley eq. 3-36). Solid round bar only — a "
                "hollow shaft needs J = pi*(d_o^4-d_i^4)/32, a different relation, not this one.",
    inputs={"dia_mm": "mm"},
    output=("polar_moment_mm4", "mm^4"),
    fn=lambda dia_mm: math.pi * dia_mm ** 4 / 32.0,
))

register_relation(Relation(
    name="euler_buckling_critical_load_pinned_pinned",
    description="Euler critical buckling load for a slender column: P_cr = pi^2*E*I/(K*L)^2 (Euler's "
                "column-buckling formula; Shigley Mechanical Engineering Design Table 4-2 / Timoshenko "
                "& Gere, Theory of Elastic Stability). END-FIXITY ASSUMPTION, STATED EXPLICITLY AND "
                "BAKED IN (not a free input, by design — a boundary condition is a judgment call this "
                "catalog will not let an LLM caller silently pick a K for): PINNED-PINNED, K=1.0 (both "
                "ends free to rotate, restrained against lateral translation) — the classical/original "
                "Euler case, per the relation name. A genuinely different end condition needs a "
                "DIFFERENT K and is NOT this relation: fixed-free K=2.0 (e.g. a free-standing leg fixed "
                "only at its base — the classic 'buckling leg' case), fixed-fixed K=0.5, fixed-pinned "
                "K~=0.699. Do NOT use this pinned-pinned relation for an actual fixed-free "
                "leg/column — its higher P_cr would OVERSTATE the true critical load (a fixed-free "
                "column's real P_cr is only 1/4 of the pinned-pinned value for the same L), a false "
                "'safe' signal. No fixed-free relation is in this catalog yet — that case is currently "
                "'unknown', which is correct, not a shortcoming to paper over.",
    inputs={"modulus_mpa": "MPa", "moment_of_inertia_mm4": "mm^4", "length_mm": "mm"},
    output=("critical_load_n", "N"),
    fn=lambda modulus_mpa, moment_of_inertia_mm4, length_mm: (
        (math.pi ** 2) * modulus_mpa * moment_of_inertia_mm4 / (length_mm ** 2)
    ),
))

register_relation(Relation(
    name="bolt_preload_from_torque",
    description="Short-form bolted-joint torque-tension relation, rearranged for preload: F = T/(K*d) "
                "(from T = K*F*d, Shigley Mechanical Engineering Design eq. 8-25), where d is the "
                "bolt's nominal (major) diameter. K-FACTOR ASSUMPTION, STATED EXPLICITLY AND BAKED IN "
                "(not a free input — a friction/lubrication condition this catalog will not let an LLM "
                "caller silently pick a coefficient for): K=0.20, the commonly-cited baseline for "
                "non-plated, as-received ('black finish') steel fasteners under typical dry conditions "
                "(Shigley Table 8-15). Real K varies roughly 0.15-0.25+ depending on lubrication, "
                "plating, and thread condition — do NOT trust this relation's output for a lubricated, "
                "plated, or otherwise atypical fastener without a different, explicitly-stated K.",
    inputs={"torque_nmm": "N*mm", "dia_mm": "mm"},
    output=("preload_n", "N"),
    fn=lambda torque_nmm, dia_mm: torque_nmm / (0.20 * dia_mm),
))

register_relation(Relation(
    name="bolt_shear_stress_from_transverse_force",
    description="Nominal (average) direct shear stress in a bolt/pin shank under a SINGLE-SHEAR "
                "transverse (perpendicular-to-axis) force: tau = F/A, A = pi*d^2/4 (the shank's "
                "circular cross-section) — the standard first-order bolt/pin direct-shear check in any "
                "machine design handbook (e.g. Shigley Mechanical Engineering Design, direct shear of "
                "a pin/bolt in a lap joint). ASSUMES SINGLE SHEAR (one shear plane, e.g. one clamped "
                "interface) — a DOUBLE-shear joint (two shear planes, e.g. a bolt through a "
                "fork/clevis) has TWICE the shear area and needs tau=F/(2A), a different relation, not "
                "this one. Does not include a thread-root stress-concentration factor (human wall — "
                "see the fatigue exclusion below).",
    inputs={"force_n": "N", "dia_mm": "mm"},
    output=("shear_stress_mpa", "MPa"),
    fn=lambda force_n, dia_mm: force_n / (math.pi * dia_mm ** 2 / 4.0),
))

# --- 2026-08-04 additions: gear-ratio kinematics (speed + torque out of a simple gear/belt/chain mesh) -
# Both relations model a single two-member mesh (spur/helical gear pair, or an equivalent belt/chain
# sprocket pair) purely from tooth counts — a standard kinematics-textbook pair of relations, and, per
# this catalog's rule, EXPLICITLY IDEAL/LOSSLESS: neither relation asserts, models, or implies any real
# mechanical-efficiency number (friction, backlash, slip) — see each description below.

register_relation(Relation(
    name="gear_ratio_speed_out",
    description="Output rotational speed of a simple two-gear mesh (or an equivalent belt/chain "
                "sprocket-tooth-ratio drive), from the input speed and the tooth counts of the driving "
                "(in) and driven (out) members: rpm_out = rpm_in * teeth_in / teeth_out — the standard "
                "kinematic gear-ratio relation, following directly from the constraint that the two "
                "members share the same pitch-line velocity at the mesh point (teeth_in teeth of the "
                "driver pass the mesh point for every teeth_out teeth of the driven member, per "
                "revolution). IDEAL, LOSSLESS: assumes a rigid, no-slip, zero-backlash mesh — real "
                "mechanical efficiency is lower (mesh friction, bearing drag, belt slip, backlash), so "
                "an actual measured output speed can differ from this theoretical value. This relation "
                "does not model, assume, or imply any specific real-world efficiency figure — it is a "
                "theoretical kinematic ratio only, never a measured or de-rated one.",
    inputs={"rpm_in": "rpm", "teeth_in": "count", "teeth_out": "count"},
    output=("rpm_out", "rpm"),
    fn=lambda rpm_in, teeth_in, teeth_out: rpm_in * teeth_in / teeth_out,
))

register_relation(Relation(
    name="gear_ratio_torque_out",
    description="Output torque of a simple two-gear mesh (or an equivalent belt/chain sprocket-tooth-"
                "ratio drive), from the input torque and the tooth counts of the driving (in) and "
                "driven (out) members: torque_out_nmm = torque_in_nmm * teeth_out / teeth_in — the "
                "standard kinematic gear-ratio torque relation, the mirror image of "
                "gear_ratio_speed_out (torque scales by the INVERSE tooth ratio, teeth_out/teeth_in "
                "rather than teeth_in/teeth_out, so that ideal power P = T*omega is exactly conserved "
                "across the mesh). IDEAL, LOSSLESS: assumes zero mechanical loss (no mesh/bearing "
                "friction, no backlash) — real mechanical efficiency is lower, so an actual output "
                "torque is somewhat LESS than this theoretical value. This relation does not model, "
                "assume, or imply any specific real-world efficiency figure — it is a theoretical "
                "upper-bound kinematic ratio only, never a measured or de-rated one. Because both "
                "torque_in_nmm and the output are expressed in N*mm, the tooth-count ratio applies with "
                "no conversion factor.",
    inputs={"torque_in_nmm": "N*mm", "teeth_in": "count", "teeth_out": "count"},
    output=("torque_out_nmm", "N*mm"),
    fn=lambda torque_in_nmm, teeth_in, teeth_out: torque_in_nmm * teeth_out / teeth_in,
))
