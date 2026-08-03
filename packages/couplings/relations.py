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

Units are explicit in every quantity NAME (`_n`, `_mm`, `_pa`, `_g`, `_nmm`) so a mismatch is visible,
not silent. Every relation is verified against a hand-computed value in tests/couplings/.
"""

from __future__ import annotations

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
    description="Torque = force x radius (a force at a crank throw / lever arm).",
    inputs={"force_n": "N", "radius_mm": "mm"},
    output=("torque_nm", "N*m"),
    fn=lambda force_n, radius_mm: force_n * (radius_mm / 1000.0),
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
