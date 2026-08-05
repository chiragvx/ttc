"""DFM fit-socket expansion (2026-08-04) — golden-value coverage for `compute_fit()`
(packages/subsystems/fit.py) against the 7 newly-declared fit_socket CONNECTORs (`threaded_boss`,
`press_fit_boss`, `standoff`, `hex_standoff`, `pcb_stack_standoff`, `stepped_spacer`, `prop_spacer`),
exercised against REAL registered round hosts (`round_post`/`round_bar`) — mirrors
tests/backend/test_fit_ops.py's own real round_post <-> spar_joiner_sleeve proof, but calls
`compute_fit()` directly rather than going through the REST `/fit_ops` layer, since these 7 files'
own test ownership is per-subsystem (tests/subsystems/), not the shared fit-ops REST surface (that
surface's own tests already prove the REST/apply/replay path works, end to end, for the pre-existing
round_post<->spar_joiner_sleeve pair — see tests/backend/test_fit_ops.py).

Every expected value below is HAND-COMPUTED from `compute_fit()`'s own documented formula
(`host_value + clearance_mm`, packages/subsystems/fit.py:107) BEFORE this file ever calls the
function — never back-filled from a first run's own output. `round_post`'s own default `dia_mm` is
12.0 (packages/subsystems/round_post.py); `round_bar`'s own default `dia_mm` is 10.0
(packages/subsystems/round_bar.py) — both read directly from those files, not assumed."""

from __future__ import annotations

from packages.subsystems import get_subsystem_model
from packages.subsystems.fit import compute_fit
from packages.transport.app import make_demo_ledger


def _ledger_with(host_type: str, host_dia_mm: float, connector_type: str,
                  host_id: str = "host", connector_id: str = "conn"):
    """A real ledger with two REAL registered instances (no synthetic/monkeypatched subsystems) —
    `host_type`'s own `dia_mm` overridden to `host_dia_mm`, the connector left at its own defaults."""
    from packages.ledger.schema import Instance

    host_model = get_subsystem_model(host_type)
    connector_model = get_subsystem_model(connector_type)
    host_params = dict(host_model.defaults())
    host_params["dia_mm"] = host_params["dia_mm"].model_copy(update={"value": host_dia_mm})

    led = make_demo_ledger()
    led = led.model_copy(update={"instances": {
        host_id: Instance(id=host_id, subsystem_type=host_type, params=host_params),
        connector_id: Instance(id=connector_id, subsystem_type=connector_type, params=connector_model.defaults()),
    }, "root_id": host_id})
    return led


def test_threaded_boss_pilot_dia_derives_from_a_round_post_host():
    # hand computation: round_post dia_mm = 16.0 (overridden, not its own 12.0 default), clearance
    # 0.4mm -> pilot_dia_mm = 16.0 + 0.4 = 16.4
    led = _ledger_with("round_post", 16.0, "threaded_boss")
    result = compute_fit(led, "conn", "host", 0.4)
    assert result.ok, result.reason
    assert result.kind == "round"
    assert result.values == {"pilot_dia_mm": 16.4}
    assert result.dim_map == {"dia_mm": "pilot_dia_mm"}


def test_press_fit_boss_inner_dia_derives_with_a_negative_press_fit_clearance():
    # hand computation: round_post dia_mm = 12.0 (its own default), interference clearance -0.1mm
    # (schema.py::FitBinding — "negative = interference/press fit", matching this part's own stated
    # purpose of "a slightly-undersized pilot for a press-fit metal insert") -> 12.0 + (-0.1) = 11.9
    led = _ledger_with("round_post", 12.0, "press_fit_boss")
    result = compute_fit(led, "conn", "host", -0.1)
    assert result.ok, result.reason
    assert result.kind == "round"
    assert result.values == {"inner_dia_mm": 11.9}


def test_standoff_inner_dia_derives_from_a_round_bar_host():
    # hand computation: round_bar dia_mm = 10.0 (its own default), clearance 0.3mm -> 10.0 + 0.3 = 10.3
    led = _ledger_with("round_bar", 10.0, "standoff")
    result = compute_fit(led, "conn", "host", 0.3)
    assert result.ok, result.reason
    assert result.values == {"inner_dia_mm": 10.3}


def test_hex_standoff_bore_dia_derives_from_a_round_post_host():
    # hand computation: round_post dia_mm = 9.0 (overridden), clearance 0.2mm -> 9.0 + 0.2 = 9.2
    led = _ledger_with("round_post", 9.0, "hex_standoff")
    result = compute_fit(led, "conn", "host", 0.2)
    assert result.ok, result.reason
    assert result.kind == "round"
    assert result.values == {"bore_dia_mm": 9.2}
    assert result.dim_map == {"dia_mm": "bore_dia_mm"}


def test_pcb_stack_standoff_inner_dia_derives_from_a_round_bar_host():
    # hand computation: round_bar dia_mm = 10.0 (its own default), clearance 0.15mm -> 10.0 + 0.15 = 10.15
    led = _ledger_with("round_bar", 10.0, "pcb_stack_standoff")
    result = compute_fit(led, "conn", "host", 0.15)
    assert result.ok, result.reason
    assert result.values == {"inner_dia_mm": 10.15}


def test_stepped_spacer_bore_dia_derives_from_a_round_post_host():
    # hand computation: round_post dia_mm = 12.0 (its own default), clearance 0.5mm -> 12.0 + 0.5 = 12.5
    led = _ledger_with("round_post", 12.0, "stepped_spacer")
    result = compute_fit(led, "conn", "host", 0.5)
    assert result.ok, result.reason
    assert result.values == {"bore_dia_mm": 12.5}


def test_prop_spacer_inner_dia_derives_from_a_round_bar_host():
    # hand computation: round_bar dia_mm = 10.0 (its own default), clearance 0.25mm -> 10.0 + 0.25 = 10.25
    led = _ledger_with("round_bar", 10.0, "prop_spacer")
    result = compute_fit(led, "conn", "host", 0.25)
    assert result.ok, result.reason
    assert result.values == {"inner_dia_mm": 10.25}


def test_threaded_boss_refuses_a_rect_host_kind_mismatch():
    # threaded_boss's fit_socket is kind="round" -- a rect-profile host (flat_bar) must be refused
    # outright, never coerced (packages/subsystems/fit.py:74-77).
    from packages.ledger.schema import Instance

    host_model = get_subsystem_model("flat_bar")
    connector_model = get_subsystem_model("threaded_boss")
    led = make_demo_ledger()
    led = led.model_copy(update={"instances": {
        "host": Instance(id="host", subsystem_type="flat_bar", params=host_model.defaults()),
        "conn": Instance(id="conn", subsystem_type="threaded_boss", params=connector_model.defaults()),
    }, "root_id": "host"})
    result = compute_fit(led, "conn", "host", 0.0)
    assert not result.ok
    assert "round" in result.reason and "rect" in result.reason
