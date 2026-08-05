"""Piece A (2026-08-04) — the generic coupling read path: `derived_param_value` generalizes
`derived_load_n`'s exact (value, reason) contract (packages/couplings/resolve.py) to ANY registered
relation's output, selected by `Coupling.target_param` (packages/ledger/schema.py) instead of a
hardcoded output_quantity == "force_n" filter.

This is a NEW, ADDITIVE function/field — every test here also proves it does not change
`derived_load_n`/`coupling_gate_findings`'s existing behavior for a coupling that happens to ALSO set
`target_param` (a coupling can feed both the structural force-only load path AND a display self-check
at once; the two reads are fully independent)."""

from __future__ import annotations

import pytest

from packages.couplings.resolve import coupling_gate_findings, derived_load_n, derived_param_value
from packages.ledger.schema import Coupling, CouplingInput

GEAR_RATIO_PARAM = "computed_gear_ratio"


# --- the "no coupling at all" contract, mirroring derived_load_n's own ---------------------------


def test_no_matching_coupling_returns_none_none(base_ledger):
    """Mirrors derived_load_n's own contract for a part with no coupling at all (see
    tests/couplings/test_couplings.py::test_a_part_with_no_coupling_has_no_derived_load)."""
    v, reason = derived_param_value(base_ledger, "root", GEAR_RATIO_PARAM)
    assert v is None and reason is None


def test_a_pre_existing_coupling_with_no_target_param_never_matches(base_ledger):
    """`target_param` defaults to None on every coupling that predates this field — None can never
    equal a real param_name, so a pre-existing coupling (one that never sets target_param) is invisible
    to derived_param_value. This is the backward-compatibility guarantee: Piece A changes nothing about
    what an existing coupling resolves to anywhere else."""
    base_ledger.couplings = [Coupling(
        id="c1", target_instance="root", relation="force_from_mass_accel",
        inputs={"mass_g": CouplingInput(value=500.0), "accel_g": CouplingInput(value=4.0)})]
    assert base_ledger.couplings[0].target_param is None  # the default
    v, reason = derived_param_value(base_ledger, "root", GEAR_RATIO_PARAM)
    assert v is None and reason is None


def test_a_coupling_targeting_a_different_param_does_not_match(base_ledger):
    base_ledger.couplings = [Coupling(
        id="c1", target_instance="root", relation="force_from_mass_accel",
        inputs={"mass_g": CouplingInput(value=500.0), "accel_g": CouplingInput(value=4.0)},
        target_param="some_other_param")]
    v, reason = derived_param_value(base_ledger, "root", GEAR_RATIO_PARAM)
    assert v is None and reason is None


def test_a_coupling_targeting_a_different_instance_does_not_match(base_ledger):
    base_ledger.couplings = [Coupling(
        id="c1", target_instance="root", relation="force_from_mass_accel",
        inputs={"mass_g": CouplingInput(value=500.0), "accel_g": CouplingInput(value=4.0)},
        target_param=GEAR_RATIO_PARAM)]
    v, reason = derived_param_value(base_ledger, "some_other_instance", GEAR_RATIO_PARAM)
    assert v is None and reason is None


# --- known value: hand-computed golden (same formula/golden value as test_couplings.py) ----------


def test_known_relation_targeting_a_named_param_resolves(base_ledger):
    # hand-computed: 500 g at 4 g-load = 0.5 kg * 4 * 9.80665 m/s^2 = 19.6133 N
    base_ledger.couplings = [Coupling(
        id="c1", target_instance="root", relation="force_from_mass_accel",
        inputs={"mass_g": CouplingInput(value=500.0), "accel_g": CouplingInput(value=4.0)},
        target_param=GEAR_RATIO_PARAM)]
    v, reason = derived_param_value(base_ledger, "root", GEAR_RATIO_PARAM)
    assert reason is None
    assert v == pytest.approx(19.6133, abs=1e-3)


def test_multiple_couplings_targeting_the_same_param_are_summed(base_ledger):
    # hand-computed superposition:
    #   c1: 0.5 kg * 4 * 9.80665 = 19.6133 N
    #   c2: 0.2 kg * 1 * 9.80665 = 1.96133 N
    #   sum = 21.57463 N
    base_ledger.couplings = [
        Coupling(id="c1", target_instance="root", relation="force_from_mass_accel",
                 inputs={"mass_g": CouplingInput(value=500.0), "accel_g": CouplingInput(value=4.0)},
                 target_param=GEAR_RATIO_PARAM),
        Coupling(id="c2", target_instance="root", relation="force_from_mass_accel",
                 inputs={"mass_g": CouplingInput(value=200.0), "accel_g": CouplingInput(value=1.0)},
                 target_param=GEAR_RATIO_PARAM),
    ]
    v, reason = derived_param_value(base_ledger, "root", GEAR_RATIO_PARAM)
    assert reason is None
    assert v == pytest.approx(21.57463, abs=1e-3)


def test_unknown_relation_targeting_a_named_param_is_unknown_not_dropped(base_ledger):
    base_ledger.couplings = [Coupling(
        id="c1", target_instance="root", relation="fatigue_life", inputs={},
        target_param=GEAR_RATIO_PARAM)]
    v, reason = derived_param_value(base_ledger, "root", GEAR_RATIO_PARAM)
    assert v is None
    assert reason is not None and "fatigue_life" in reason


# --- fully additive: proves Piece A changes nothing about the pre-existing gate/FS path -----------


def test_target_param_does_not_change_derived_load_n_or_gate_findings(base_ledger):
    """The same coupling, with vs. without target_param set, must produce IDENTICAL derived_load_n and
    coupling_gate_findings results for the target instance -- target_param is a read-only annotation
    that must never leak into the existing force/gate logic."""
    plain = Coupling(id="c1", target_instance="root", relation="force_from_mass_accel",
                     inputs={"mass_g": CouplingInput(value=500.0), "accel_g": CouplingInput(value=4.0)})
    annotated = plain.model_copy(update={"target_param": GEAR_RATIO_PARAM})

    led_plain = base_ledger.model_copy(update={"couplings": [plain]})
    led_annotated = base_ledger.model_copy(update={"couplings": [annotated]})

    assert derived_load_n(led_plain, "root") == derived_load_n(led_annotated, "root")
    assert coupling_gate_findings(led_plain) == coupling_gate_findings(led_annotated)


def test_coupling_target_param_defaults_to_none():
    """Backward-compatible default -- constructing a Coupling exactly as every pre-Piece-A caller does
    (no target_param kwarg at all) must yield None, not require every existing call site to change."""
    c = Coupling(id="c1", target_instance="root", relation="force_from_mass_accel",
                inputs={"mass_g": CouplingInput(value=500.0), "accel_g": CouplingInput(value=4.0)})
    assert c.target_param is None
