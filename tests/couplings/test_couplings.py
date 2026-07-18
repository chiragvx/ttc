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
    assert get_relation("torque_from_force_radius").evaluate({"force_n": 1000.0, "radius_mm": 25.0}) == pytest.approx(25.0)


def test_bending_from_distributed_load():
    # M = W*L/8 = 200 * 500 / 8 = 12500 N*mm
    assert get_relation("bending_from_distributed_load").evaluate({"total_load_n": 200.0, "span_mm": 500.0}) == pytest.approx(12500.0)


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
