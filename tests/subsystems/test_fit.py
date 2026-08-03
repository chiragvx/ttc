"""packages/subsystems/fit.py::compute_fit — unit-level coverage for the rotation-safety gate and
kind-mismatch refusal, using synthetic Subsystem objects (monkeypatched into get_subsystem_model)
rather than real registry entries, since no rect-kind host/connector exists yet (that's Stage 1's
job — see prompt_builder.py's own live-generated fittable-hosts/connectors list). The round-family
happy path is already covered end-to-end via tests/backend/test_fit_ops.py's real round_post <->
spar_joiner_sleeve REST-level tests; this file covers what those real subsystems can't exercise yet."""

from __future__ import annotations

from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Instance
from packages.subsystems import add_instance
from packages.subsystems.base import FitProfile, FitSocketSpec, ParamSpec, Subsystem
from packages.subsystems.fit import compute_fit
from packages.transport.app import make_demo_ledger


def _synthetic_registry(monkeypatch, subsystems: dict[str, Subsystem]):
    def fake_get_subsystem_model(name):
        if name not in subsystems:
            raise KeyError(name)
        return subsystems[name]
    monkeypatch.setattr("packages.subsystems.get_subsystem_model", fake_get_subsystem_model)


def _rect_host(kind="rect"):
    # width/height are read from the INSTANCE's own resolved params at compute_fit time (see
    # _ledger_with below), not from anything closed over here -- this only declares the shape.
    return Subsystem(
        name="rect_host", description="", fragment="", disciplines=(),
        params=[ParamSpec("width_mm", 20.0, 1.0, 200.0, "mm"), ParamSpec("height_mm", 20.0, 1.0, 200.0, "mm")],
        fit_profile=lambda p: FitProfile(kind=kind, dims={"width_mm": p.width_mm, "height_mm": p.height_mm}),
    )


def _rect_connector():
    return Subsystem(
        name="rect_connector", description="", fragment="", disciplines=(),
        params=[ParamSpec("bore_w_mm", 10.0, 1.0, 200.0, "mm"), ParamSpec("bore_h_mm", 10.0, 1.0, 200.0, "mm")],
        fit_socket=FitSocketSpec(kind="rect", dim_params={"width_mm": "bore_w_mm", "height_mm": "bore_h_mm"}),
    )


def _ledger_with(host_type: str, connector_type: str, width: float = 20.0, height: float = 20.0):
    led = make_demo_ledger()
    led = led.model_copy(update={"instances": {
        "host": Instance(id="host", subsystem_type=host_type, params={
            "width_mm": ParameterDef(value=width, unit="mm", bounds=(1.0, 200.0)),
            "height_mm": ParameterDef(value=height, unit="mm", bounds=(1.0, 200.0)),
        }),
        "conn": Instance(id="conn", subsystem_type=connector_type, params={
            "bore_w_mm": ParameterDef(value=10.0, unit="mm", bounds=(1.0, 200.0)),
            "bore_h_mm": ParameterDef(value=10.0, unit="mm", bounds=(1.0, 200.0)),
        }),
    }, "root_id": "host"})
    return led


def test_compute_fit_accepts_a_square_rect_host(monkeypatch):
    _synthetic_registry(monkeypatch, {"rect_host": _rect_host(), "rect_connector": _rect_connector()})
    led = _ledger_with("rect_host", "rect_connector", width=20.0, height=20.0)
    result = compute_fit(led, "conn", "host", 0.0)
    assert result.ok
    assert result.values == {"bore_w_mm": 20.0, "bore_h_mm": 20.0}


def test_compute_fit_refuses_a_non_square_rect_host(monkeypatch):
    # this system never auto-solves rotation -- a bore fitted to a non-square cross-section has no
    # way to verify its orientation, so it's refused outright, never rendered as if it were correct.
    _synthetic_registry(monkeypatch, {"rect_host": _rect_host(), "rect_connector": _rect_connector()})
    led = _ledger_with("rect_host", "rect_connector", width=30.0, height=20.0)
    result = compute_fit(led, "conn", "host", 0.0)
    assert not result.ok
    assert "not square" in result.reason
    assert "rotation" in result.reason


def test_compute_fit_refuses_a_kind_mismatch(monkeypatch):
    _synthetic_registry(monkeypatch, {
        "rect_host": _rect_host(kind="round"),   # a "round" host...
        "rect_connector": _rect_connector(),     # ...but a "rect" socket
    })
    led = _ledger_with("rect_host", "rect_connector", width=20.0, height=20.0)
    result = compute_fit(led, "conn", "host", 0.0)
    assert not result.ok
    assert "round" in result.reason and "rect" in result.reason


def test_compute_fit_applies_clearance_to_every_dimension(monkeypatch):
    _synthetic_registry(monkeypatch, {"rect_host": _rect_host(), "rect_connector": _rect_connector()})
    led = _ledger_with("rect_host", "rect_connector", width=20.0, height=20.0)
    result = compute_fit(led, "conn", "host", -0.15)  # interference/press fit
    assert result.ok
    assert result.values == {"bore_w_mm": 19.85, "bore_h_mm": 19.85}
