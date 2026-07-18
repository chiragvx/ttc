"""Self-check: geometric validator (packages/truth_plane/validate.py) + POST /validate + the vision
seam (packages/agents/vision_validator.py / OpenRouterDeltaProvider.judge_image).

The geometric backbone is deterministic and needs no model — it catches the failures the user actually
hit (floating parts, engulfed parts, degenerate builds). The visual half is gated behind VISION_MODEL
and cleanly skipped otherwise (a missing visual check never fabricates a pass)."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from packages.transport.app import create_app

HAS_B123D = importlib.util.find_spec("build123d") is not None

pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")


def _make(led_parts):
    """Build a ledger with the given (subsystem, id, transform_kwargs, params) parts."""
    from packages.transport.app import make_demo_ledger
    from packages.subsystems import add_instance
    from packages.ledger.parameter import ParameterDef
    from packages.ledger.schema import Transform

    led = make_demo_ledger()
    for stype, iid, tf, params in led_parts:
        led = add_instance(led, stype, iid)
        if tf:
            led.instances[iid].transform = Transform(**tf)
        for name, val in params.items():
            led.instances[iid].params[name] = ParameterDef(value=float(val), unit="mm", bounds=(-3000.0, 3000.0))
    return led


def test_single_part_passes():
    from packages.truth_plane.validate import validate_geometry
    led = _make([("bracket", "b1", {}, {})])
    r = validate_geometry(led)
    assert r.ok
    assert not r.issues


def test_touching_bwb_and_wings_pass():
    from packages.truth_plane.validate import validate_geometry
    led = _make([
        ("bwb_fuselage", "body", {}, {"span_mm": 500, "tip_chord_mm": 130}),
        ("wing_panel", "wr", {"x_mm": 250, "y_mm": 67, "z_mm": 8.7}, {"side_sign": 1, "root_chord_mm": 130}),
        ("wing_panel", "wl", {"x_mm": -250, "y_mm": 67, "z_mm": 8.7}, {"side_sign": -1, "root_chord_mm": 130}),
    ])
    r = validate_geometry(led)
    assert r.ok, r.summary
    assert not any(i.check == "connectivity" for i in r.issues)


def test_floating_part_flagged_as_disconnected():
    from packages.truth_plane.validate import validate_geometry
    led = _make([
        ("bwb_fuselage", "body", {}, {"span_mm": 500}),
        ("wing_panel", "floater", {"x_mm": 0, "y_mm": 700, "z_mm": 0}, {}),
    ])
    r = validate_geometry(led)
    conn = [i for i in r.issues if i.check == "connectivity"]
    assert conn, "a wing floating 700mm away must be flagged disconnected"
    assert "floater" in conn[0].instances
    assert r.ok  # connectivity is a WARNING, not an error — doesn't flip ok


def test_validate_endpoint_runs_geometric_without_a_vision_model():
    c = TestClient(create_app())
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "bwb_fuselage"})
    c.post("/instance_ops", json={"op": "add_instance", "subsystem_type": "wing_panel",
                                   "x_mm": 0, "y_mm": 700, "z_mm": 0})
    r = c.post("/validate", json={"intent": "a BWB flying wing"}).json()
    assert r["vision_enabled"] is False        # no VISION_MODEL set in the test env
    assert r["visual"] is None
    assert any(i["check"] == "connectivity" for i in r["geometric"]["issues"])


def test_judge_image_parses_a_vision_verdict_through_the_seam():
    # the vision path itself, exercised via the injectable _post seam (no live model / no network)
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    fake = {"choices": [{"message": {"content":
        '{"ok": false, "issues": [{"severity": "warning", "message": "left wing sweeps forward"}], '
        '"summary": "asymmetric sweep"}'}}]}
    prov = OpenRouterDeltaProvider(api_key="x", post=lambda **kw: fake)
    v = prov.judge_image(image_png=b"PNG", prompt="judge", vision_model="some/vision-model")
    assert v["ok"] is False
    assert v["issues"][0]["message"] == "left wing sweeps forward"


def test_judge_image_returns_none_on_an_unparseable_verdict_never_a_fabricated_pass():
    # 2026-07-19 review (HIGH): an absent/truncated/non-JSON reply must NOT become {"ok": True} —
    # that would silently flip a real problem into a fabricated visual pass. None = inconclusive.
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    for junk in ("the wing looks fine to me", "", "```\ntruncated", "[1, 2, 3]"):
        prov = OpenRouterDeltaProvider(api_key="x",
                                       post=lambda junk=junk, **kw: {"choices": [{"message": {"content": junk}}]})
        assert prov.judge_image(image_png=b"P", prompt="p", vision_model="m") is None, junk


def test_visual_validation_skipped_cleanly_without_a_model(monkeypatch):
    from packages.agents.vision_validator import validate_visual
    from packages.transport.app import make_demo_ledger
    from packages.subsystems import add_instance
    monkeypatch.delenv("VISION_MODEL", raising=False)
    led = add_instance(make_demo_ledger(), "bracket", "b1")
    # no VISION_MODEL, no key -> returns None (never fabricates a verdict)
    assert validate_visual(led, "a bracket", vision_model=None, api_key=None) is None
