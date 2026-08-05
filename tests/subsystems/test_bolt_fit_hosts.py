"""Bolt-blank fit_profile HOSTs (2026-08-05) — golden-value coverage for `compute_fit()`
(packages/subsystems/fit.py) against the 5 bolt/screw-family subsystems (`socket_cap_bolt_blank`,
`hex_bolt_blank`, `button_head_bolt_blank`, `flat_head_bolt_blank`, `thumb_screw`), found missing
live: a standoff/spacer CONNECTOR trying to fit around any of these got REJECTED with "declares no
fit_profile", even though "derive the standoff bore from the actual screw" is exactly the DFM-cited
use case fit_socket exists for (see standoff.py's own fit_socket comment). Every expected value below
is HAND-COMPUTED from `compute_fit()`'s own documented formula (`host_value + clearance_mm`,
packages/subsystems/fit.py:107) BEFORE this file ever calls the function, using each bolt's own
default `dia2_mm` (the shank/thread diameter -- `dia1_mm` is the unrelated HEAD diameter), read
directly from each file (all five default to 4.0mm), never back-filled from a first run's output."""

from __future__ import annotations

from packages.subsystems import get_subsystem_model
from packages.subsystems.fit import compute_fit
from packages.transport.app import make_demo_ledger


def _ledger_with(host_type: str, connector_type: str, host_id: str = "host", connector_id: str = "conn"):
    """A real ledger with two REAL registered instances at their own catalog defaults (no
    synthetic/monkeypatched subsystems, no overrides -- every bolt-family default dia2_mm is 4.0mm,
    read directly from each subsystem file, so the expected values are computed from that)."""
    from packages.ledger.schema import Instance

    host_model = get_subsystem_model(host_type)
    connector_model = get_subsystem_model(connector_type)
    led = make_demo_ledger()
    led = led.model_copy(update={"instances": {
        host_id: Instance(id=host_id, subsystem_type=host_type, params=host_model.defaults()),
        connector_id: Instance(id=connector_id, subsystem_type=connector_type, params=connector_model.defaults()),
    }, "root_id": host_id})
    return led


def test_socket_cap_bolt_blank_is_a_valid_fit_host_for_a_standoff():
    # hand computation: socket_cap_bolt_blank's own default dia2_mm = 4.0, clearance 0.4 -> 4.4
    led = _ledger_with("socket_cap_bolt_blank", "standoff")
    result = compute_fit(led, "conn", "host", 0.4)
    assert result.ok, result.reason
    assert result.kind == "round"
    assert result.values == {"inner_dia_mm": 4.4}
    assert result.dim_map == {"dia_mm": "inner_dia_mm"}


def test_hex_bolt_blank_is_a_valid_fit_host_for_a_standoff():
    # hand computation: hex_bolt_blank's own default dia2_mm = 4.0, clearance 0.3 -> 4.3
    led = _ledger_with("hex_bolt_blank", "standoff")
    result = compute_fit(led, "conn", "host", 0.3)
    assert result.ok, result.reason
    assert result.values == {"inner_dia_mm": 4.3}


def test_button_head_bolt_blank_is_a_valid_fit_host_for_a_standoff():
    # hand computation: button_head_bolt_blank's own default dia2_mm = 4.0, clearance 0.2 -> 4.2
    led = _ledger_with("button_head_bolt_blank", "standoff")
    result = compute_fit(led, "conn", "host", 0.2)
    assert result.ok, result.reason
    assert result.values == {"inner_dia_mm": 4.2}


def test_flat_head_bolt_blank_is_a_valid_fit_host_with_a_press_fit_negative_clearance():
    # hand computation: flat_head_bolt_blank's own default dia2_mm = 4.0, interference -0.1 -> 3.9
    led = _ledger_with("flat_head_bolt_blank", "standoff")
    result = compute_fit(led, "conn", "host", -0.1)
    assert result.ok, result.reason
    assert result.values == {"inner_dia_mm": 3.9}


def test_thumb_screw_is_a_valid_fit_host_for_a_standoff():
    # hand computation: thumb_screw's own default dia2_mm = 4.0, clearance 0.5 -> 4.5
    led = _ledger_with("thumb_screw", "standoff")
    result = compute_fit(led, "conn", "host", 0.5)
    assert result.ok, result.reason
    assert result.values == {"inner_dia_mm": 4.5}


def test_bolt_family_fit_profile_reads_dia2_mm_the_shank_not_dia1_mm_the_head():
    # The specific bug this fix targets: dia1_mm (the head) and dia2_mm (the shank) are BOTH present
    # on every bolt-blank part -- confirm the derived value tracks dia2_mm (4.0) and is NOT anywhere
    # near dia1_mm (8.0 for socket_cap_bolt_blank), which would be a wrong-param regression.
    led = _ledger_with("socket_cap_bolt_blank", "standoff")
    result = compute_fit(led, "conn", "host", 0.0)
    assert result.ok, result.reason
    assert result.values == {"inner_dia_mm": 4.0}  # == dia2_mm + 0, NOT dia1_mm (8.0) + 0
