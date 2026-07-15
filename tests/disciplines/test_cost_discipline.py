"""Cost discipline — analytic $ readout across every subsystem, opt-in budget gate."""

from __future__ import annotations

import pytest

from packages.disciplines import all_discipline_findings, get_discipline
from packages.disciplines import cost as cost_module
from packages.disciplines.cost import cost_usd
from packages.ledger.bom import material
from packages.ledger.gates import evaluate_export_gates
from packages.subsystems import get_subsystem


def _seeded_active(base_ledger, name: str):
    """Seed a subsystem's defaults + flip subsystem_type. Mirrors the tests/subsystems/conftest helper.

    Also reconciles assembly-template children (2026-07-03, packages/subsystems/assembly_template.py)
    — a safe no-op for every subsystem that doesn't declare `assembly_children`, and required for one
    that does (e.g. "table"): its root instance has no geometry/volume of its own, so `cost_usd`
    would silently see 0.0 without materializing the real children that carry it."""
    from packages.subsystems.assembly_template import reconcile_children

    led = get_subsystem(name).seed_defaults(base_ledger)
    pm = led.project_metadata.model_copy(update={"subsystem_type": name})
    led = led.model_copy(update={"project_metadata": pm})
    return reconcile_children(led, led.root_id)


def test_cost_discipline_registered():
    assert "cost" in {get_discipline(n).name for n in ("cost",)}


@pytest.mark.parametrize("name", ["bracket", "enclosure", "standoff", "lbracket",
                                   "uchannel", "panel", "washer", "table"])
def test_every_subsystem_has_a_finite_positive_cost(base_ledger, name):
    """The whole point of Cost as a discipline: every part gets a $ readout."""
    led = _seeded_active(base_ledger, name)
    assert cost_usd(led) > 0.0


def test_cost_formula_matches_material_and_time(base_ledger):
    led = _seeded_active(base_ledger, "washer")  # OD20 ID8 t2, PLA
    v = get_subsystem("washer").volume_mm3(led)
    mat = material(led.domains.structure.material_profile)  # PLA
    mass_kg = mat.density_g_per_mm3 * v / 1000.0
    # read the LIVE module value, not a `from ... import` snapshot — cost_module.MACHINE_RATE_USD_PER_HR
    # is mutable global state since set_machine_rate() (2026-07-15); a stale imported copy would
    # silently diverge from what cost_usd() itself reads if another test's override leaked in.
    expected = mass_kg * mat.cost_per_kg_usd + (v / 5.0 / 3600.0) * cost_module.MACHINE_RATE_USD_PER_HR
    assert cost_usd(led) == pytest.approx(expected)


def test_no_gate_contribution_without_budget(base_ledger):
    """Without max_cost_usd set, Cost is a pure readout — no gate reason."""
    led = _seeded_active(base_ledger, "bracket")
    reasons, _ = all_discipline_findings(led)
    assert not any("cost" in r.lower() for r in reasons)


def test_gate_blocks_when_over_budget(base_ledger):
    """With a tiny budget, Cost contributes an export-blocking reason."""
    led = _seeded_active(base_ledger, "bracket")
    gc = led.global_constraints.model_copy(update={"max_cost_usd": 0.01})
    led = led.model_copy(update={"global_constraints": gc})
    reasons, _ = all_discipline_findings(led)
    assert any("exceeds max_cost_usd" in r for r in reasons)


def test_export_gate_composes_cost(base_ledger):
    """The Cost gate flows through gates.evaluate_export_gates via all_discipline_findings."""
    led = _seeded_active(base_ledger, "bracket")
    gc = led.global_constraints.model_copy(update={"max_cost_usd": 0.01})
    led = led.model_copy(update={"global_constraints": gc})
    result = evaluate_export_gates(led, extra_findings=all_discipline_findings)
    assert any("exceeds max_cost_usd" in r for r in result.reasons)


def test_gate_stays_quiet_when_within_budget(base_ledger):
    led = _seeded_active(base_ledger, "washer")
    gc = led.global_constraints.model_copy(update={"max_cost_usd": 10000.0})
    led = led.model_copy(update={"global_constraints": gc})
    reasons, _ = all_discipline_findings(led)
    assert not any("exceeds max_cost_usd" in r for r in reasons)


def test_set_machine_rate_changes_cost_usd(base_ledger):
    """packages/catalog/bootstrap.py's injection seam (2026-07-15) — cost_usd() reads the module
    global at call time, so overriding it must actually change the computed cost."""
    led = _seeded_active(base_ledger, "washer")
    try:
        before = cost_usd(led)
        cost_module.set_machine_rate(cost_module.MACHINE_RATE_USD_PER_HR * 10.0)
        after = cost_usd(led)
        assert after > before
    finally:
        cost_module.reset_machine_rate()


def test_reset_machine_rate_restores_the_hardcoded_default():
    try:
        cost_module.set_machine_rate(999.0)
        assert cost_module.MACHINE_RATE_USD_PER_HR == 999.0
        cost_module.reset_machine_rate()
        assert cost_module.MACHINE_RATE_USD_PER_HR == cost_module._DEFAULT_MACHINE_RATE_USD_PER_HR
    finally:
        cost_module.reset_machine_rate()
