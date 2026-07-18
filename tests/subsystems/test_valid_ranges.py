"""Closed-form invariant-valid slider ranges (2026-07-19) — packages/subsystems/valid_ranges.py.

These are the ranges the frontend clamps each slider to so a human drag can never reach a CONFLICT.
They clamp to the PHYSICALLY-VALID range (cross-field invariants), NOT the advisory recommended
bounds — see the module docstring and packages/ledger/parameter.py."""

from __future__ import annotations

from packages.ledger.parameter import ParameterDef
from packages.subsystems import add_instance, get_subsystem_model
from packages.subsystems.valid_ranges import valid_param_ranges
from packages.transport.app import make_demo_ledger


def _set(led, iid, name, value, bounds):
    led.instances[iid].params[name] = ParameterDef(value=value, unit="mm", bounds=bounds)


def test_blend_taper_clamped_to_half_span():
    # THE live failure this exists to prevent: blend_taper_mm doubled must not exceed span_mm.
    led = make_demo_ledger()
    led = add_instance(led, "bwb_fuselage", "bwb1")
    _set(led, "bwb1", "span_mm", 600.0, (200.0, 3000.0))
    ranges = valid_param_ranges(get_subsystem_model("bwb_fuselage"), led, "bwb1")
    lo, hi = ranges["blend_taper_mm"]
    assert lo == 0.0
    # valid max is span/2 = 300 (2*blend_taper <= span), tightly bounded, far below recommended 1500
    assert 299.0 <= hi <= 300.0, hi


def test_valid_max_tracks_span_when_span_changes():
    # raising span_mm must WIDEN blend_taper_mm's valid max (the live cross-param behavior the WS
    # response refreshes every drag tick)
    led = make_demo_ledger()
    led = add_instance(led, "bwb_fuselage", "bwb1")
    model = get_subsystem_model("bwb_fuselage")
    _set(led, "bwb1", "span_mm", 600.0, (200.0, 3000.0))
    hi_small = valid_param_ranges(model, led, "bwb1")["blend_taper_mm"][1]
    _set(led, "bwb1", "span_mm", 1600.0, (200.0, 3000.0))
    hi_big = valid_param_ranges(model, led, "bwb1")["blend_taper_mm"][1]
    assert hi_big > hi_small
    assert 799.0 <= hi_big <= 800.0, hi_big


def test_reversed_taper_bounds_tip_below_centerbody():
    # tip_chord_mm must stay below centerbody_chord_mm (a BWB blends thick->thin, never reverse) —
    # so tip's valid max is the current centerbody chord, not its own recommended 600.
    led = make_demo_ledger()
    led = add_instance(led, "bwb_fuselage", "bwb1")
    _set(led, "bwb1", "centerbody_chord_mm", 250.0, (50.0, 1500.0))
    ranges = valid_param_ranges(get_subsystem_model("bwb_fuselage"), led, "bwb1")
    lo, hi = ranges["tip_chord_mm"]
    assert hi <= 250.5, hi  # cannot exceed the centerbody chord


def test_unconstrained_param_keeps_full_recommended_range():
    # sweep_deg has no cross-field invariant — its valid range must be its full recommended range,
    # never artificially narrowed.
    led = make_demo_ledger()
    led = add_instance(led, "bwb_fuselage", "bwb1")
    ranges = valid_param_ranges(get_subsystem_model("bwb_fuselage"), led, "bwb1")
    lo, hi = ranges["sweep_deg"]
    spec = next(s for s in get_subsystem_model("bwb_fuselage").params if s.name == "sweep_deg")
    assert lo == spec.min and hi == spec.max


def test_current_value_outside_recommended_stays_reachable():
    # an LLM-set value beyond the recommended envelope must remain inside the search range (so the
    # slider can still show/reach it) — the widening rule in valid_param_ranges.
    led = make_demo_ledger()
    led = add_instance(led, "bwb_fuselage", "bwb1")
    # sweep_deg recommended max is 45; force 60 (out of recommended, but no invariant forbids it)
    _set_deg = ParameterDef(value=60.0, unit="deg", bounds=(-30.0, 45.0))
    led.instances["bwb1"].params["sweep_deg"] = _set_deg
    ranges = valid_param_ranges(get_subsystem_model("bwb_fuselage"), led, "bwb1")
    lo, hi = ranges["sweep_deg"]
    assert hi >= 60.0, hi  # the current 60 is reachable on the slider


def test_walk_tests_the_search_bound_not_just_returns_it():
    # Regression (2026-07-19 review): _walk() must not return search_hi/search_lo as a valid endpoint
    # WITHOUT testing it. A strict-inequality invariant that fails exactly at the recommended max,
    # with every sampled point below passing, would otherwise hand back an invalid max. Build a
    # synthetic subsystem whose only invariant is `x < 100.0` (strictly) and confirm the valid max is
    # just under 100, never 100 itself (100 is invalid) nor the widened search bound.
    from types import SimpleNamespace
    from packages.subsystems.base import ParamSpec, Subsystem
    from packages.subsystems.valid_ranges import _valid_interval_around

    sub = Subsystem(
        name="_synthetic_strict",
        description="test-only",
        fragment="",
        disciplines=(),
        params=[ParamSpec("x", value=50.0, min=0.0, max=100.0, unit="mm")],
        invariants=lambda p: [] if p.x < 100.0 else ["x must be strictly < 100"],
    )
    # search range is the recommended [0, 100]; current=50 passes. The upper bound 100 FAILS the
    # strict invariant, so the returned valid max must be < 100 (bisected), not 100.
    lo, hi = _valid_interval_around(sub, {"x": 50.0}, "x", 0.0, 100.0, 50.0)
    assert lo == 0.0
    assert 99.9 <= hi < 100.0, hi  # tight to the boundary, but strictly below the failing bound
    # sanity: the boundary value itself must genuinely pass
    assert not sub.invariants(SimpleNamespace(x=hi))
    assert sub.invariants(SimpleNamespace(x=100.0))  # 100 really does fail


def test_bracket_edge_distance_bounds_hole_diameter():
    # a non-aerospace wedge part: bracket's edge-distance invariant should bound hole_diameter_mm's
    # valid max below its recommended max when the plate is small — proves this isn't bwb-specific.
    led = make_demo_ledger()
    led = add_instance(led, "bracket", "b1")
    model = get_subsystem_model("bracket")
    ranges = valid_param_ranges(model, led, "b1")
    # every param's valid range must at minimum contain its current value and be non-inverted
    ns_vals = {s.name: led.instances["b1"].params.get(s.name).value
               if led.instances["b1"].params.get(s.name) else s.value for s in model.params}
    for name, (lo, hi) in ranges.items():
        assert lo <= hi, f"{name} inverted: [{lo}, {hi}]"
        assert lo - 1e-6 <= ns_vals[name] <= hi + 1e-6, f"{name} current {ns_vals[name]} not in [{lo}, {hi}]"
