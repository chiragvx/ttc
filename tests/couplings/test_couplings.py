"""Phase 2 (2026-07-19) — the coupling primitive: loads DERIVED through a registered relation catalog,
not stated scalars. The pump story made computable, with "unknown blocks" honesty.

Relations are verified against hand-computed values (the catalog is the ground truth, never the LLM)."""

from __future__ import annotations

import math

import pytest

from packages.couplings import (
    coupling_gate_findings,
    derived_load_n,
    get_relation,
    resolve_couplings,
)
from packages.couplings.relations import RELATION_REGISTRY
from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Coupling, CouplingInput
from packages.subsystems import add_instance
from packages.transport.app import make_demo_ledger


# --- relation math, against hand-computed values ---
def test_force_from_pressure_area():
    # 2 MPa over 500 mm^2 = 2e6 Pa * 500e-6 m^2 = 1000 N
    assert get_relation("force_from_pressure_area").evaluate({"pressure_pa": 2e6, "area_mm2": 500.0}) == pytest.approx(1000.0)


def test_force_from_mass_accel():
    # 500 g at 4 g-load = 0.5 kg * 4 * 9.80665 = 19.6133 N
    assert get_relation("force_from_mass_accel").evaluate({"mass_g": 500.0, "accel_g": 4.0}) == pytest.approx(19.6133, abs=1e-3)


def test_torque_from_force_radius():
    # 2026-08-03: output standardized to torque_nmm (N*mm), was torque_nm (N*m) — see the unit-mismatch
    # fix note in relations.py. T = F*r = 1000 N * 25 mm = 25000 N*mm (the same physical torque as the
    # old 25 N*m value, just expressed in mm — 25 N*m == 25000 N*mm).
    assert get_relation("torque_from_force_radius").evaluate({"force_n": 1000.0, "radius_mm": 25.0}) == pytest.approx(25000.0)


def test_torque_output_unit_matches_shear_stress_input_unit_no_1000x_mismatch():
    # PINS the defect fix: torque_from_force_radius's declared output quantity name+unit must be
    # BIT-FOR-BIT the same quantity name+unit shear_stress_from_torque_radius declares for its torque
    # input, so a future coupling-chaining feature can wire one straight into the other with NO silent
    # factor-of-1000 error. This is a regression test for a defect that was dormant only because
    # chaining does not exist yet (a coupling's input today is only a literal or a single part param).
    torque_rel = get_relation("torque_from_force_radius")
    shear_rel = get_relation("shear_stress_from_torque_radius")
    assert torque_rel.output == ("torque_nmm", "N*mm")
    assert "torque_nmm" in shear_rel.inputs
    assert shear_rel.inputs["torque_nmm"] == "N*mm"
    # the general form of the pin: whatever name/unit torque_from_force_radius emits must equal
    # whatever name/unit shear_stress_from_torque_radius expects for that same quantity.
    out_name, out_unit = torque_rel.output
    assert out_name in shear_rel.inputs
    assert shear_rel.inputs[out_name] == out_unit


def test_bending_from_distributed_load():
    # M = W*L/8 = 200 * 500 / 8 = 12500 N*mm
    assert get_relation("bending_from_distributed_load").evaluate({"total_load_n": 200.0, "span_mm": 500.0}) == pytest.approx(12500.0)


def test_stress_from_force_area():
    # sigma = F/A = 2000 N / 100 mm^2 = 20 MPa (N/mm^2)
    assert get_relation("stress_from_force_area").evaluate({"force_n": 2000.0, "area_mm2": 100.0}) == pytest.approx(20.0)


def test_deflection_of_cantilever_beam():
    # delta = P*L^3/(3*E*I) = 100 * 200^3 / (3 * 200000 * 8000) = 8e8 / 4.8e9 = 1/6 mm
    assert get_relation("deflection_of_cantilever_beam").evaluate(
        {"force_n": 100.0, "length_mm": 200.0, "modulus_mpa": 200_000.0, "moment_of_inertia_mm4": 8000.0}
    ) == pytest.approx(1.0 / 6.0, abs=1e-6)


def test_spring_force_from_rate_deflection():
    # F = k*x = 5 N/mm * 10 mm = 50 N
    assert get_relation("spring_force_from_rate_deflection").evaluate(
        {"spring_rate_n_per_mm": 5.0, "deflection_mm": 10.0}
    ) == pytest.approx(50.0)


def test_shear_stress_from_torque_radius():
    # tau = T*r/J = 50000 N*mm * 10 mm / 5000 mm^4 = 100 MPa (N/mm^2)
    assert get_relation("shear_stress_from_torque_radius").evaluate(
        {"torque_nmm": 50_000.0, "radius_mm": 10.0, "polar_moment_mm4": 5000.0}
    ) == pytest.approx(100.0)


def test_unknown_relation_raises_on_lookup():
    with pytest.raises(KeyError):
        get_relation("fatigue_life")  # deliberately NOT in the catalog — a human wall


# --- the resolver + the pump propagation ---
def _pump(pressure_pa):
    led = make_demo_ledger()
    led = add_instance(led, "enclosure", "casing")
    led = add_instance(led, "round_bar", "crank")
    led.instances["casing"].params["chamber_pressure_pa"] = ParameterDef(value=pressure_pa, unit="Pa", bounds=(0.0, 5e7))
    led.couplings = [Coupling(id="cpl", target_instance="crank", relation="force_from_pressure_area",
        inputs={"pressure_pa": CouplingInput(from_instance="casing", from_param="chamber_pressure_pa"),
                "area_mm2": CouplingInput(value=500.0)})]
    return led


def test_derived_load_from_a_source_param():
    v, reason = derived_load_n(_pump(2_000_000.0), "crank")
    assert reason is None
    assert v == pytest.approx(1000.0)


def test_changing_the_source_repropagates_the_load():
    # THE Phase 2 proof: raise casing pressure -> the crank's derived load recomputes (the crack story)
    lo, _ = derived_load_n(_pump(2_000_000.0), "crank")
    hi, _ = derived_load_n(_pump(3_000_000.0), "crank")
    assert hi > lo
    assert hi == pytest.approx(1500.0)


def test_a_part_with_no_coupling_has_no_derived_load():
    led = add_instance(make_demo_ledger(), "bracket", "b1")
    v, reason = derived_load_n(led, "b1")
    assert v is None and reason is None  # no coupling at all — not "unknown", just absent


# --- "unknown blocks" ---
def test_unwired_relation_is_unknown_and_blocks_the_gate():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="fatigue_life", inputs={})]
    res = resolve_couplings(led)[0]
    assert not res.is_known and res.value is None
    reasons, unknowns = coupling_gate_findings(led)
    assert "coupling:c1" in unknowns
    assert any("c1" in r and "unknown" in r for r in reasons)


def test_missing_source_instance_is_unknown():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="force_from_pressure_area",
        inputs={"pressure_pa": CouplingInput(from_instance="ghost", from_param="p"),
                "area_mm2": CouplingInput(value=1.0)})]
    res = resolve_couplings(led)[0]
    assert not res.is_known
    assert "ghost" in res.reason


def test_missing_input_wiring_is_unknown():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    # relation needs pressure_pa AND area_mm2; wire only one
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="force_from_pressure_area",
        inputs={"pressure_pa": CouplingInput(value=1e6)})]
    res = resolve_couplings(led)[0]
    assert not res.is_known
    assert "area_mm2" in res.reason


def test_coupling_input_rejects_both_or_neither_form():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CouplingInput(value=1.0, from_instance="x", from_param="y")  # both
    with pytest.raises(ValidationError):
        CouplingInput()  # neither


def test_non_physical_derived_value_is_unknown_not_grounded():
    # 2026-07-19 review (CRITICAL): a relation returning NaN/inf/negative must be UNKNOWN, never fed to
    # FS as a grounded load. Negative pressure -> negative force -> must block.
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c", target_instance="crank", relation="force_from_pressure_area",
        inputs={"pressure_pa": CouplingInput(value=-1e6), "area_mm2": CouplingInput(value=500.0)})]
    res = resolve_couplings(led)[0]
    assert not res.is_known and res.value is None
    assert "non-physical" in res.reason


def test_multiple_force_couplings_superimpose():
    # 2026-07-19 review (HIGH): two force couplings on one target must SUM (superposition), not silently
    # drop all but the first.
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [
        Coupling(id="c1", target_instance="crank", relation="force_from_pressure_area",
                 inputs={"pressure_pa": CouplingInput(value=2e6), "area_mm2": CouplingInput(value=500.0)}),  # 1000
        Coupling(id="c2", target_instance="crank", relation="force_from_mass_accel",
                 inputs={"mass_g": CouplingInput(value=1000.0), "accel_g": CouplingInput(value=2.0)}),  # ~19.6
    ]
    v, reason = derived_load_n(led, "crank")
    assert reason is None
    assert v == pytest.approx(1000.0 + 1.0 * 2.0 * 9.80665, abs=1e-3)


def test_one_unknown_contributor_makes_the_whole_superposed_load_unknown():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [
        Coupling(id="c1", target_instance="crank", relation="force_from_pressure_area",
                 inputs={"pressure_pa": CouplingInput(value=2e6), "area_mm2": CouplingInput(value=500.0)}),  # known
        Coupling(id="c2", target_instance="crank", relation="fatigue_life", inputs={}),  # unknown
    ]
    v, reason = derived_load_n(led, "crank")
    assert v is None and reason is not None


def test_unit_mismatch_between_source_param_and_relation_is_unknown():
    # 2026-07-19 review (MEDIUM): sourcing an area input from a length (mm) param is a mis-wiring.
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led = add_instance(led, "bracket", "src")
    led.instances["src"].params["some_len"] = ParameterDef(value=500.0, unit="mm", bounds=(0.0, 1e4))
    led.couplings = [Coupling(id="c", target_instance="crank", relation="force_from_pressure_area",
        inputs={"pressure_pa": CouplingInput(value=2e6),
                "area_mm2": CouplingInput(from_instance="src", from_param="some_len")})]
    res = resolve_couplings(led)[0]
    assert not res.is_known
    assert "unit mismatch" in res.reason


def test_equivalent_unit_labels_do_not_false_flag():
    # a param labelled 'mm2' must satisfy a relation wanting 'mm^2' (same unit, different spelling) —
    # the normalizer must NOT reject an equivalent unit.
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led = add_instance(led, "bracket", "src")
    led.instances["src"].params["area"] = ParameterDef(value=500.0, unit="mm2", bounds=(0.0, 1e6))
    led.couplings = [Coupling(id="c", target_instance="crank", relation="force_from_pressure_area",
        inputs={"pressure_pa": CouplingInput(value=2e6),
                "area_mm2": CouplingInput(from_instance="src", from_param="area")})]
    res = resolve_couplings(led)[0]
    assert res.is_known and res.value == pytest.approx(1000.0)


def test_registry_has_the_v1_catalog():
    for name in ("force_from_mass_accel", "force_from_pressure_area",
                 "torque_from_force_radius", "bending_from_distributed_load"):
        assert name in RELATION_REGISTRY


def test_registry_has_the_2026_07_31_additions():
    for name in ("stress_from_force_area", "deflection_of_cantilever_beam",
                 "spring_force_from_rate_deflection", "shear_stress_from_torque_radius"):
        assert name in RELATION_REGISTRY


# --- 2026-08-03 additions: cantilever bending, section properties, Euler buckling, bolted joint -----
# Every expected value below was HAND-COMPUTED from the closed-form formula (calculator arithmetic,
# shown inline) BEFORE running any code — never back-filled from this implementation's own output.

def test_bending_from_cantilever_point_load():
    # Euler-Bernoulli cantilever, tip point load: M = F*L = 150 N * 400 mm = 60000 N*mm
    assert get_relation("bending_from_cantilever_point_load").evaluate(
        {"force_n": 150.0, "length_mm": 400.0}
    ) == pytest.approx(60000.0)


def test_bending_from_cantilever_distributed_load():
    # Euler-Bernoulli cantilever, uniform distributed load: M = W*L/2 = 300 N * 800 mm / 2 = 120000 N*mm
    assert get_relation("bending_from_cantilever_distributed_load").evaluate(
        {"total_load_n": 300.0, "span_mm": 800.0}
    ) == pytest.approx(120000.0)


def test_second_moment_of_area_rectangular():
    # I = b*h^3/12 = 10 mm * 20^3 mm^3 / 12 = 10*8000/12 = 80000/12 = 6666.6667 mm^4
    assert get_relation("second_moment_of_area_rectangular").evaluate(
        {"width_mm": 10.0, "height_mm": 20.0}
    ) == pytest.approx(6666.66667, abs=1e-3)


def test_second_moment_of_area_circular():
    # I = pi*d^4/64 = pi * 20^4 / 64 = pi * 160000/64 = pi*2500 = 7853.98163 mm^4 (pi=3.14159265)
    assert get_relation("second_moment_of_area_circular").evaluate(
        {"dia_mm": 20.0}
    ) == pytest.approx(7853.98163, abs=1e-3)


def test_polar_second_moment_of_area_circular():
    # J = pi*d^4/32 = pi * 160000/32 = pi*5000 = 15707.96327 mm^4 (pi=3.14159265) — exactly 2x the
    # second_moment_of_area_circular value above (J=2I for a circular section), a handy cross-check.
    assert get_relation("polar_second_moment_of_area_circular").evaluate(
        {"dia_mm": 20.0}
    ) == pytest.approx(15707.96327, abs=1e-3)


def test_euler_buckling_critical_load_pinned_pinned():
    # P_cr = pi^2*E*I/L^2 (K=1, pinned-pinned) = pi^2 * 70000 MPa * 10000 mm^4 / 500^2 mm^2
    #      = 9.869604401 * 700,000,000 / 250,000 = 9.869604401 * 2800 = 27634.8923 N
    assert get_relation("euler_buckling_critical_load_pinned_pinned").evaluate(
        {"modulus_mpa": 70000.0, "moment_of_inertia_mm4": 10000.0, "length_mm": 500.0}
    ) == pytest.approx(27634.8923, abs=1e-2)


def test_bolt_preload_from_torque():
    # F = T/(K*d) = 20000 N*mm / (0.20 * 8 mm) = 20000 / 1.6 = 12500 N
    assert get_relation("bolt_preload_from_torque").evaluate(
        {"torque_nmm": 20000.0, "dia_mm": 8.0}
    ) == pytest.approx(12500.0)


def test_bolt_shear_stress_from_transverse_force():
    # tau = F/A, A = pi*d^2/4 = pi*10^2/4 = 25*pi = 78.5398163 mm^2
    # tau = 5000 N / 78.5398163 mm^2 = 200/pi = 63.6619772 MPa
    assert get_relation("bolt_shear_stress_from_transverse_force").evaluate(
        {"force_n": 5000.0, "dia_mm": 10.0}
    ) == pytest.approx(63.6619772, abs=1e-3)


def test_registry_has_the_2026_08_03_additions():
    for name in ("bending_from_cantilever_point_load", "bending_from_cantilever_distributed_load",
                 "second_moment_of_area_rectangular", "second_moment_of_area_circular",
                 "polar_second_moment_of_area_circular", "euler_buckling_critical_load_pinned_pinned",
                 "bolt_preload_from_torque", "bolt_shear_stress_from_transverse_force"):
        assert name in RELATION_REGISTRY


def test_no_fatigue_or_stress_concentration_relations_registered():
    # HUMAN WALL, explicitly respected: fatigue/S-N-curve/stress-concentration relations need empirical
    # data (S-N curves, Kt factors) this catalog has no grounded closed-form source for — assert none
    # snuck into the registry under any name.
    banned_substrings = ("fatigue", "s_n_curve", "sncurve", "stress_concentration", "kt_factor", "miner")
    for name in RELATION_REGISTRY:
        low = name.lower().replace("-", "_")
        assert not any(b in low for b in banned_substrings), f"{name!r} looks like a banned human-wall relation"


# --- Defect 1 regression (2026-08-03): a KNOWN torque/moment/preload coupling must NOT vanish as if
# the part had no coupling at all, and must BLOCK export like any other unknown safety input — before
# this fix, a moment/torque-only coupling fell straight out of the `output_quantity == "force_n"`
# filter, `derived_load_n` returned `(None, None)` (indistinguishable from "no coupling"), the real
# solver then solved a case against the hardcoded default load, and the export gate saw a fully-
# populated, seemingly-grounded FS with nothing to complain about.

def test_torque_only_coupling_is_distinguishable_from_no_coupling_at_all():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="torque_from_force_radius",
        inputs={"force_n": CouplingInput(value=1000.0), "radius_mm": CouplingInput(value=25.0)})]
    # the coupling itself resolves fine — this is a real, KNOWN torque, not an unresolvable relation.
    res = resolve_couplings(led)[0]
    assert res.is_known and res.output_quantity == "torque_nmm"
    v, reason = derived_load_n(led, "crank")
    assert v is None
    # THE pin: must be distinguishable from test_a_part_with_no_coupling_has_no_derived_load's (None, None)
    assert reason is not None
    assert "c1" in reason


def test_moment_only_coupling_is_distinguishable_from_no_coupling_at_all():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="bending_from_distributed_load",
        inputs={"total_load_n": CouplingInput(value=200.0), "span_mm": CouplingInput(value=500.0)})]
    v, reason = derived_load_n(led, "crank")
    assert v is None and reason is not None


def test_preload_only_coupling_is_distinguishable_from_no_coupling_at_all():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="bolt_preload_from_torque",
        inputs={"torque_nmm": CouplingInput(value=20000.0), "dia_mm": CouplingInput(value=8.0)})]
    v, reason = derived_load_n(led, "crank")
    assert v is None and reason is not None


def test_torque_only_coupling_blocks_the_export_gate_as_an_unknown():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="torque_from_force_radius",
        inputs={"force_n": CouplingInput(value=1000.0), "radius_mm": CouplingInput(value=25.0)})]
    reasons, unknowns = coupling_gate_findings(led)
    assert "coupling:c1" in unknowns
    assert any("c1" in r and "torque_nmm" in r for r in reasons)


def test_moment_only_coupling_blocks_the_export_gate_as_an_unknown():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="bending_from_distributed_load",
        inputs={"total_load_n": CouplingInput(value=200.0), "span_mm": CouplingInput(value=500.0)})]
    reasons, unknowns = coupling_gate_findings(led)
    assert "coupling:c1" in unknowns
    assert any("c1" in r and "moment_nmm" in r for r in reasons)


def test_preload_only_coupling_blocks_the_export_gate_as_an_unknown():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="bolt_preload_from_torque",
        inputs={"torque_nmm": CouplingInput(value=20000.0), "dia_mm": CouplingInput(value=8.0)})]
    reasons, unknowns = coupling_gate_findings(led)
    assert "coupling:c1" in unknowns
    assert any("c1" in r and "preload_n" in r for r in reasons)


def test_a_force_coupling_alongside_a_moment_coupling_prefers_the_force_and_does_not_block():
    # a REAL force is derivable here — it is used (matching `_iter_coarse_cantilever_fs`'s own
    # longstanding "prefer force, don't double-count/conflict with a bending-moment reading" precedent,
    # packages/transport/app.py), and does NOT block just because the part also carries a moment the
    # force-only path can't separately consume. Combining multiple simultaneous load types into one FS
    # is a real but SEPARATE multi-load-case question (a human-wall item), not a fabricated-load one —
    # over-blocking a part with a perfectly real, non-fabricated derived force would be its own bug
    # (see tests/backend/test_validate.py::test_validate_endpoint_prefers_a_force_coupling_over_a_
    # moment_one_when_both_exist for the same precedent exercised end-to-end).
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [
        Coupling(id="c_force", target_instance="crank", relation="force_from_pressure_area",
                 inputs={"pressure_pa": CouplingInput(value=2e6), "area_mm2": CouplingInput(value=500.0)}),
        Coupling(id="c_moment", target_instance="crank", relation="bending_from_distributed_load",
                 inputs={"total_load_n": CouplingInput(value=200.0), "span_mm": CouplingInput(value=500.0)}),
    ]
    v, reason = derived_load_n(led, "crank")
    assert reason is None
    assert v == pytest.approx(1000.0)  # the force_from_pressure_area value, not blocked by the moment
    reasons, unknowns = coupling_gate_findings(led)
    assert "coupling:c_moment" not in unknowns
    assert unknowns == [] and reasons == []


def test_stress_only_coupling_is_not_a_load_bearing_claim_and_does_not_block():
    # do-not-over-block precedent: a coupling whose ONLY output is stress_mpa is NOT a load-bearing
    # claim on the part — it must not be treated the same as a torque/moment/preload claim.
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="stress_from_force_area",
        inputs={"force_n": CouplingInput(value=2000.0), "area_mm2": CouplingInput(value=100.0)})]
    v, reason = derived_load_n(led, "crank")
    assert v is None and reason is None  # absent, not blocked — same as no coupling at all
    reasons, unknowns = coupling_gate_findings(led)
    assert unknowns == [] and reasons == []


def test_deflection_only_coupling_is_not_a_load_bearing_claim_and_does_not_block():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="deflection_of_cantilever_beam",
        inputs={"force_n": CouplingInput(value=100.0), "length_mm": CouplingInput(value=200.0),
                "modulus_mpa": CouplingInput(value=200_000.0),
                "moment_of_inertia_mm4": CouplingInput(value=8000.0)})]
    v, reason = derived_load_n(led, "crank")
    assert v is None and reason is None
    reasons, unknowns = coupling_gate_findings(led)
    assert unknowns == [] and reasons == []


# --- 2026-08-04 additions: gear-ratio kinematics (speed + torque out of a simple gear/belt/chain mesh)
# Every expected value below was HAND-COMPUTED from the closed-form formula (calculator arithmetic,
# shown inline) BEFORE writing any code — never back-filled from this implementation's own output.

def test_gear_ratio_speed_out():
    # rpm_out = rpm_in * teeth_in / teeth_out = 3000 rpm * 20 / 60 = 3000 * (1/3) = 1000.0 rpm
    assert get_relation("gear_ratio_speed_out").evaluate(
        {"rpm_in": 3000.0, "teeth_in": 20.0, "teeth_out": 60.0}
    ) == pytest.approx(1000.0)


def test_gear_ratio_speed_out_non_round_ratio():
    # rpm_out = rpm_in * teeth_in / teeth_out = 1750 rpm * 18 / 54
    # 1750 * 18 = 31500; 31500 / 54 = 583.333... (54*583 = 31482, remainder 18, 18/54 = 1/3) -> 583.3333 rpm
    assert get_relation("gear_ratio_speed_out").evaluate(
        {"rpm_in": 1750.0, "teeth_in": 18.0, "teeth_out": 54.0}
    ) == pytest.approx(583.3333, abs=1e-3)


def test_gear_ratio_torque_out():
    # torque_out_nmm = torque_in_nmm * teeth_out / teeth_in = 500 N*mm * 60 / 20 = 500 * 3 = 1500.0 N*mm
    assert get_relation("gear_ratio_torque_out").evaluate(
        {"torque_in_nmm": 500.0, "teeth_in": 20.0, "teeth_out": 60.0}
    ) == pytest.approx(1500.0)


def test_gear_ratio_torque_out_non_round_ratio():
    # torque_out_nmm = torque_in_nmm * teeth_out / teeth_in = 120 N*mm * 54 / 18 = 120 * 3 = 360.0 N*mm
    assert get_relation("gear_ratio_torque_out").evaluate(
        {"torque_in_nmm": 120.0, "teeth_in": 18.0, "teeth_out": 54.0}
    ) == pytest.approx(360.0)


def test_gear_ratio_relations_conserve_ideal_power_across_the_same_mesh():
    # Bonus hand-derived consistency check (not a new physics claim — a direct algebraic consequence of
    # both formulas being defined as the exact inverse of each other): for one ideal, lossless mesh with
    # rpm_in=3000, teeth_in=20, teeth_out=60, torque_in_nmm=500 -> rpm_out=1000 (test above),
    # torque_out_nmm=1500 (test above). Ideal power P ~ T*omega is conserved iff T_in*rpm_in ==
    # T_out*rpm_out (the rpm-to-omega constant cancels on both sides):
    # T_in*rpm_in = 500 * 3000 = 1,500,000
    # T_out*rpm_out = 1500 * 1000 = 1,500,000 -- equal, as the ideal/lossless assumption requires.
    rpm_out = get_relation("gear_ratio_speed_out").evaluate(
        {"rpm_in": 3000.0, "teeth_in": 20.0, "teeth_out": 60.0}
    )
    torque_out = get_relation("gear_ratio_torque_out").evaluate(
        {"torque_in_nmm": 500.0, "teeth_in": 20.0, "teeth_out": 60.0}
    )
    assert 500.0 * 3000.0 == pytest.approx(torque_out * rpm_out)


def test_gear_ratio_relations_are_explicitly_disclosed_as_ideal_lossless():
    # Both descriptions MUST state the ideal/lossless assumption explicitly — this registry does not let
    # a relation imply a real-world mechanical-efficiency number that was never grounded.
    for name in ("gear_ratio_speed_out", "gear_ratio_torque_out"):
        desc = get_relation(name).description.lower()
        assert "ideal" in desc and "lossless" in desc


def test_gear_ratio_teeth_unit_is_consistent_between_the_two_relations():
    speed_rel = get_relation("gear_ratio_speed_out")
    torque_rel = get_relation("gear_ratio_torque_out")
    assert speed_rel.inputs["teeth_in"] == torque_rel.inputs["teeth_in"] == "count"
    assert speed_rel.inputs["teeth_out"] == torque_rel.inputs["teeth_out"] == "count"


def test_gear_ratio_torque_out_unit_matches_other_torque_nmm_relations_in_registry():
    # Continuing the 2026-08-03 1000x-unit-mismatch-fix discipline: every torque quantity in this
    # catalog must share the SAME unit label ("N*mm"), never a silent mix of N*mm and N*m.
    gear_torque = get_relation("gear_ratio_torque_out")
    assert gear_torque.inputs["torque_in_nmm"] == "N*mm"
    assert gear_torque.output == ("torque_out_nmm", "N*mm")
    force_radius = get_relation("torque_from_force_radius")
    bolt_preload = get_relation("bolt_preload_from_torque")
    assert force_radius.output == ("torque_nmm", "N*mm")
    assert bolt_preload.inputs["torque_nmm"] == "N*mm"


def test_registry_has_the_2026_08_04_additions():
    for name in ("gear_ratio_speed_out", "gear_ratio_torque_out"):
        assert name in RELATION_REGISTRY


def test_shear_stress_only_coupling_is_not_a_load_bearing_claim_and_does_not_block():
    led = add_instance(make_demo_ledger(), "round_bar", "crank")
    led.couplings = [Coupling(id="c1", target_instance="crank", relation="shear_stress_from_torque_radius",
        inputs={"torque_nmm": CouplingInput(value=50_000.0), "radius_mm": CouplingInput(value=10.0),
                "polar_moment_mm4": CouplingInput(value=5000.0)})]
    v, reason = derived_load_n(led, "crank")
    assert v is None and reason is None
    reasons, unknowns = coupling_gate_findings(led)
    assert unknowns == [] and reasons == []
