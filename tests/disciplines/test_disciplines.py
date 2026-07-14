"""Disciplines registry + the Thermal discipline (proof of the registry pattern).

Verifies: registry membership; thermal is opt-in (inactive by default → zero behavior change); the L0
material service-temp gate blocks honestly; the L1 heat-load margin is `unknown` (blocks) until a real
solver is wired; and the export gate composes discipline findings via the `extra_findings` seam.
"""

from __future__ import annotations

from packages.disciplines import (
    DISCIPLINE_REGISTRY,
    active_discipline_fragments,
    active_disciplines,
    all_discipline_findings,
    get_discipline,
)
from packages.ledger.bom import MATERIAL_DB, material
from packages.ledger.gates import evaluate_export_gates
from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import MasterParametricLedger, ThermalDomain


def _with_thermal(ledger: MasterParametricLedger, *, operating: float, power: float = 0.0,
                  material_profile: str | None = None) -> MasterParametricLedger:
    thermal = ThermalDomain(
        operating_temp_c=ParameterDef(value=operating, unit="degC", bounds=(-40.0, 200.0)),
        power_dissipation_w=ParameterDef(value=power, unit="W", bounds=(0.0, 500.0)),
    )
    structure = ledger.domains.structure
    if material_profile is not None:
        structure = structure.model_copy(update={"material_profile": material_profile})
    domains = ledger.domains.model_copy(update={"thermal": thermal, "structure": structure})
    return ledger.model_copy(update={"domains": domains})


# --- registry ---------------------------------------------------------------

def test_registry_has_core_three():
    assert {"structures", "manufacturing", "thermal"} <= set(DISCIPLINE_REGISTRY)
    assert get_discipline("thermal").name == "thermal"


def test_structures_and_manufacturing_always_active(base_ledger):
    names = {d.name for d in active_disciplines(base_ledger)}
    assert {"structures", "manufacturing"} <= names


# --- thermal is opt-in: zero behavior change when absent ---------------------

def test_thermal_inactive_by_default(base_ledger):
    assert "thermal" not in {d.name for d in active_disciplines(base_ledger)}
    assert all_discipline_findings(base_ledger) == ([], [])


def test_thermal_active_when_present(base_ledger):
    led = _with_thermal(base_ledger, operating=25.0)
    assert "thermal" in {d.name for d in active_disciplines(led)}


# --- L0: closed-form material service-temp gate (a real block today) ---------

def test_l0_blocks_when_operating_exceeds_material(base_ledger):
    # base material is PLA (service ~55°C); 80°C must block
    led = _with_thermal(base_ledger, operating=80.0, material_profile="PLA")
    reasons, unknowns = all_discipline_findings(led)
    assert any("service temp" in r for r in reasons)
    assert unknowns == []  # no heat load → no unknown, just a deterministic block


def test_l0_ok_within_limit(base_ledger):
    led = _with_thermal(base_ledger, operating=40.0, material_profile="PLA")
    assert all_discipline_findings(led) == ([], [])


def test_l0_material_upgrade_clears_block(base_ledger):
    # 80°C fails on PLA (55) but passes on ABS (90)
    assert all_discipline_findings(_with_thermal(base_ledger, operating=80.0, material_profile="ABS")) == ([], [])


# --- L1: heat load → unknown until the solver is wired (Inversion #1) --------

def test_l1_power_load_is_unknown(base_ledger):
    led = _with_thermal(base_ledger, operating=25.0, power=10.0)
    reasons, unknowns = all_discipline_findings(led)
    assert "thermal_margin_c" in unknowns
    assert any("not yet wired" in r for r in reasons)


# --- export gate composition via the extra_findings seam ---------------------

def test_export_gate_composes_thermal(base_ledger):
    led = _with_thermal(base_ledger, operating=80.0, material_profile="PLA")
    result = evaluate_export_gates(led, extra_findings=all_discipline_findings)
    assert not result.eligible
    assert any("service temp" in r for r in result.reasons)


def test_export_gate_unchanged_without_thermal(base_ledger):
    # same ledger, no thermal domain: adding extra_findings must not change the outcome
    a = evaluate_export_gates(base_ledger)
    b = evaluate_export_gates(base_ledger, extra_findings=all_discipline_findings)
    assert a.reasons == b.reasons and a.unknowns == b.unknowns


# --- material DB carries the new allowable ----------------------------------

def test_all_materials_have_service_temp():
    for name in MATERIAL_DB:
        assert material(name).service_temp_c > 0


# --- prompt fragments follow activation -------------------------------------

def test_fragments_include_thermal_only_when_active(base_ledger):
    off = active_discipline_fragments(base_ledger)
    on = active_discipline_fragments(_with_thermal(base_ledger, operating=25.0))
    assert "Structures" in off and "Manufacturing" in off
    assert "Thermal" not in off
    assert "Thermal" in on
