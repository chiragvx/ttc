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


def test_a_connection_declared_part_is_not_falsely_flagged_floating():
    # Phase 1 (2026-07-19): a part joined by a typed Connection counts as connected even if its bbox
    # happens not to overlap — so the mate solver places the wings on the body tips, and the
    # connectivity check must NOT call them floating.
    from packages.truth_plane.validate import validate_geometry
    from packages.ledger.schema import Connection, InterfaceRef
    led = _make([
        ("bwb_fuselage", "body", {}, {"span_mm": 500, "tip_chord_mm": 130, "sweep_deg": 15, "dihedral_deg": 2}),
        ("wing_panel", "wr", {}, {"side_sign": 1, "root_chord_mm": 130}),
        ("wing_panel", "wl", {}, {"side_sign": -1, "root_chord_mm": 130}),
    ])
    led.connections = [
        Connection(id="cr", a=InterfaceRef(instance_id="wr", interface="root"),
                   b=InterfaceRef(instance_id="body", interface="tip_right")),
        Connection(id="cl", a=InterfaceRef(instance_id="wl", interface="root"),
                   b=InterfaceRef(instance_id="body", interface="tip_left")),
    ]
    r = validate_geometry(led)
    assert not any(i.check == "connectivity" for i in r.issues), r.summary
    assert not any(i.check == "connections" for i in r.issues)


def test_dangling_connection_surfaces_in_the_self_check():
    from packages.truth_plane.validate import validate_geometry
    from packages.ledger.schema import Connection, InterfaceRef
    led = _make([("bwb_fuselage", "body", {}, {"span_mm": 500})])
    led.connections = [Connection(id="bad", a=InterfaceRef(instance_id="body", interface="tip_right"),
                                  b=InterfaceRef(instance_id="ghost", interface="root"))]
    r = validate_geometry(led)
    assert any(i.check == "connections" for i in r.issues)


def test_visual_validation_skipped_cleanly_without_a_model(monkeypatch):
    from packages.agents.vision_validator import validate_visual
    from packages.transport.app import make_demo_ledger
    from packages.subsystems import add_instance
    monkeypatch.delenv("VISION_MODEL", raising=False)
    led = add_instance(make_demo_ledger(), "bracket", "b1")
    # no VISION_MODEL, no key -> returns None (never fabricates a verdict)
    assert validate_visual(led, "a bracket", vision_model=None, api_key=None) is None


# --- validate_visual's OWN verdict-processing logic (2026-07-22, mutation-sweep follow-up) ------
# Every test above either skips validate_visual entirely (not configured) or exercises judge_image
# in isolation via the injectable `post` seam. Nothing previously drove validate_visual all the way
# through a REAL (fake) vision verdict — the exact "never fabricate a pass from a garbled reply"
# logic its own module docstring calls out was completely untested end-to-end. validate_visual
# builds its OpenRouterDeltaProvider internally (no injection point on its own signature), so these
# monkeypatch the judge_image METHOD on the class itself, the same way monkeypatch.setattr is used
# elsewhere in this suite to stand in for a real model reply.

def _visual_ledger():
    from packages.transport.app import make_demo_ledger
    from packages.subsystems import add_instance
    return add_instance(make_demo_ledger(), "bracket", "b1")


def test_visual_validation_treats_a_non_boolean_ok_as_inconclusive_not_a_pass(monkeypatch):
    # A vision model can reply with "ok": "true" (a truthy STRING, not a bool) -- LLMs are not
    # reliable about JSON types. Must be treated as inconclusive (None), never fabricated into a pass.
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    from packages.agents.vision_validator import validate_visual
    monkeypatch.setattr(OpenRouterDeltaProvider, "judge_image",
                        lambda self, **kw: {"ok": "true", "issues": [], "summary": "looks fine"})
    result = validate_visual(_visual_ledger(), "a bracket", vision_model="some/vision-model", api_key="x")
    assert result is None


def test_visual_validation_treats_a_non_dict_verdict_as_inconclusive_not_a_crash(monkeypatch):
    # judge_image's own contract already returns None for a non-dict verdict, but validate_visual's
    # isinstance guard must independently hold too (defense in depth) -- must not raise.
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    from packages.agents.vision_validator import validate_visual
    monkeypatch.setattr(OpenRouterDeltaProvider, "judge_image", lambda self, **kw: [1, 2, 3])
    result = validate_visual(_visual_ledger(), "a bracket", vision_model="some/vision-model", api_key="x")
    assert result is None


def test_visual_validation_ok_is_false_when_a_warning_issue_is_flagged_even_if_verdict_says_ok(monkeypatch):
    # A model can say "ok": true while ALSO listing a warning-severity issue (sloppy/contradictory
    # output) -- the fail-safe must win: any flagged warning forces ok=False, matching
    # test_judge_image_parses_a_vision_verdict_through_the_seam's own fixture shape (just with ok=True).
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    from packages.agents.vision_validator import validate_visual
    monkeypatch.setattr(OpenRouterDeltaProvider, "judge_image", lambda self, **kw: {
        "ok": True, "issues": [{"severity": "warning", "message": "left wing sweeps forward"}],
        "summary": "asymmetric sweep"})
    result = validate_visual(_visual_ledger(), "a bracket", vision_model="some/vision-model", api_key="x")
    assert result is not None
    assert result.ok is False


def test_visual_validation_clamps_an_error_severity_issue_to_warning(monkeypatch):
    # A vision judgment is always advisory -- packages/truth_plane/validate.py uses "error" severity
    # for hard-blocking geometric failures, and a subjective visual opinion must never carry the same
    # weight. A model that emits severity="error" anyway (nothing upstream constrains its output)
    # must be downgraded to "warning", never pass through as "error".
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    from packages.agents.vision_validator import validate_visual
    monkeypatch.setattr(OpenRouterDeltaProvider, "judge_image", lambda self, **kw: {
        "ok": False, "issues": [{"severity": "error", "message": "totally wrong shape"}],
        "summary": "bad"})
    result = validate_visual(_visual_ledger(), "a bracket", vision_model="some/vision-model", api_key="x")
    assert result is not None
    assert result.issues[0].severity == "warning"
