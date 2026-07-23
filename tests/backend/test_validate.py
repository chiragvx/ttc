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


def test_mismatched_face_bracket_mate_surfaces_as_an_actionable_connections_warning():
    # 2026-07-22 antenna-bracket follow-up: lbracket's wall_mount (fixed -X normal) only mates
    # CLEANLY against enclosure's `right` face -- connecting it to `left` (the natural symmetric
    # choice for a second, opposite-side antenna bracket) still resolves a placement but leaves the
    # bracket embedded/facing the wrong way. This must not be a SILENT bad render: the self-check
    # has to surface it as a "connections" warning (not "connectivity" -- a declared Connection
    # counts as joined) so the already-shipped auto-correct gate (shouldAutoCorrect.ts, H7 fix)
    # fires on it instead of the copilot's reply reporting a clean, joined assembly.
    from packages.truth_plane.validate import validate_geometry
    from packages.ledger.schema import Connection, InterfaceRef
    led = _make([
        ("enclosure", "box", {}, {}),
        ("lbracket", "brk", {}, {}),
    ])
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="brk", interface="wall_mount"),
                   b=InterfaceRef(instance_id="box", interface="left")),
    ]
    r = validate_geometry(led)
    connections_issues = [i for i in r.issues if i.check == "connections"]
    assert len(connections_issues) == 1
    assert "need a rotation to mate" in connections_issues[0].message
    # not flagged as floating/disconnected -- the declared Connection counts as joined, which is
    # exactly why the "connections" channel (not "connectivity") has to carry this signal
    assert not any(i.check == "connectivity" for i in r.issues)


def test_coincident_comparable_size_parts_flagged_as_interference():
    # 2026-07-22 -- THE bug this check exists for: two identical lbrackets forced to the exact same
    # world position (no connection between them) -- this is what a botched self-correction actually
    # produced live (a connection-mated part's sibling fell back to auto-layout, which is blind to
    # where the mated part already sits). Neither `embedding` (equal volumes, ratio check fails) nor
    # `connectivity` (bbox-touching counts as "joined") catches this -- `interference` must.
    from packages.truth_plane.validate import validate_geometry
    led = _make([
        ("lbracket", "brk_a", {"x_mm": 0, "y_mm": 0, "z_mm": 0}, {}),
        ("lbracket", "brk_b", {"x_mm": 0, "y_mm": 0, "z_mm": 0}, {}),
    ])
    r = validate_geometry(led)
    interference = [i for i in r.issues if i.check == "interference"]
    assert len(interference) == 1
    assert set(interference[0].instances) == {"brk_a", "brk_b"}
    assert r.ok  # warning, not error -- never blocks export


def test_comparable_size_parts_connected_are_not_flagged_as_interference():
    # Two identical lbrackets, mated wall_mount<->wall_mount (both interfaces share the SAME fixed
    # -X normal, so this is a "rotation-needed" mate per placement.py -- the solver still translates
    # them to the exact same position, same as the coincident case above). The declared Connection
    # is what must exempt this from `interference` -- it's already reported, correctly, as a
    # `connections` rotation-needed warning; it must not ALSO double-report under a new check name.
    from packages.truth_plane.validate import validate_geometry
    from packages.ledger.schema import Connection, InterfaceRef
    led = _make([("lbracket", "ba", {}, {}), ("lbracket", "bb", {}, {})])
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="ba", interface="wall_mount"),
                   b=InterfaceRef(instance_id="bb", interface="wall_mount")),
    ]
    r = validate_geometry(led)
    assert not any(i.check == "interference" for i in r.issues), r.summary
    assert any(i.check == "connections" for i in r.issues)  # still caught, just under the right name


def test_small_part_inside_big_part_is_not_flagged_as_interference():
    # A small standoff fully inside a much bigger enclosure, no connection -- today's ordinary
    # ambiguous "maybe a legitimate internal component" case (embedding's own territory, info-only).
    # The size-ratio gate must exempt this from the NEW, more confident `interference` check too.
    from packages.truth_plane.validate import validate_geometry
    led = _make([
        ("enclosure", "box", {}, {"box_width_mm": 120, "box_depth_mm": 90, "box_height_mm": 50}),
        ("standoff", "post", {"x_mm": 0, "y_mm": 0, "z_mm": 0}, {}),
    ])
    r = validate_geometry(led)
    assert not any(i.check == "interference" for i in r.issues), r.summary
    assert any(i.check == "embedding" for i in r.issues)  # still flagged, just as the ambiguous heads-up


def test_clean_bracket_enclosure_mate_is_not_flagged_as_interference():
    # The one clean, correct mate shipped earlier this session (lbracket.wall_mount <-> enclosure's
    # +X-normal face): touches flush, never truly interpenetrates in 3D -- confirms the check doesn't
    # fire on ordinary, correctly-flush-mounted geometry.
    from packages.truth_plane.validate import validate_geometry
    from packages.ledger.schema import Connection, InterfaceRef
    led = _make([("enclosure", "box", {}, {}), ("lbracket", "brk", {}, {})])
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="brk", interface="wall_mount"),
                   b=InterfaceRef(instance_id="box", interface="right")),
    ]
    r = validate_geometry(led)
    assert not any(i.check == "interference" for i in r.issues), r.summary


def test_auto_layout_clustering_an_ordinary_part_near_an_airframe_body_is_not_interference():
    # assembly.py's 2026-07-20 two-lane auto-layout cursor DELIBERATELY seeds an airframe-defining
    # body's lane and an ordinary system part's lane independently, so an untouched system part can
    # legitimately land at/inside the airframe's own footprint pre-connection -- a real, EXPECTED
    # mid-build state, not a placement mistake. The comparable-size gate (bracket volume << wing
    # volume) must exempt this, or every ordinary multi-part build would spuriously self-correct.
    from packages.truth_plane.validate import validate_geometry
    led = _make([("naca_wing", "wing", {}, {}), ("bracket", "brk", {}, {})])
    r = validate_geometry(led)
    assert not any(i.check == "interference" for i in r.issues), r.summary


def _with_lbracket_wall_mount_keepout(monkeypatch, keepout_mm: float):
    # 2026-07-22 -- no real subsystem sets keepout_mm > 0 yet (deliberately deferred domain
    # judgment), so this monkeypatches lbracket's registered model for the duration of one test --
    # reverted automatically by pytest's monkeypatch fixture, never a permanent catalog change.
    import dataclasses
    from packages.subsystems import SUBSYSTEM_MODELS, get_subsystem_model
    model = get_subsystem_model("lbracket")
    new_interfaces = [
        dataclasses.replace(spec, keepout_mm=keepout_mm) if spec.name == "wall_mount" else spec
        for spec in model.interfaces
    ]
    monkeypatch.setitem(SUBSYSTEM_MODELS, "lbracket", dataclasses.replace(model, interfaces=new_interfaces))


def test_keepout_violation_is_flagged(monkeypatch):
    _with_lbracket_wall_mount_keepout(monkeypatch, 10.0)
    from packages.truth_plane.validate import validate_geometry
    # lbracket "brk" at the origin -> wall_mount world origin is (0, 0, leg_a_mm/2) = (0, 0, 20).
    # A standoff placed right next to that point (well within the 10mm keepout) with NO connection.
    led = _make([
        ("lbracket", "brk", {"x_mm": 0, "y_mm": 0, "z_mm": 0}, {}),
        ("standoff", "post", {"x_mm": 5, "y_mm": 0, "z_mm": 20}, {}),
    ])
    r = validate_geometry(led)
    keepout = [i for i in r.issues if i.check == "keepout"]
    assert len(keepout) == 1, r.summary
    assert set(keepout[0].instances) == {"brk", "post"}
    assert r.ok  # warning, not error


def test_keepout_does_not_fire_on_the_legitimately_connected_partner(monkeypatch):
    _with_lbracket_wall_mount_keepout(monkeypatch, 10.0)
    from packages.truth_plane.validate import validate_geometry
    from packages.ledger.schema import Connection, InterfaceRef
    led = _make([("enclosure", "box", {}, {}), ("lbracket", "brk", {}, {})])
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="brk", interface="wall_mount"),
                   b=InterfaceRef(instance_id="box", interface="right")),
    ]
    r = validate_geometry(led)
    # "box" IS within 10mm of brk's wall_mount (that's the whole point of a flush mate) but it's the
    # legitimately-connected partner for that exact interface -- must not be flagged.
    assert not any(i.check == "keepout" for i in r.issues), r.summary


def test_keepout_does_not_fire_when_nothing_is_within_range(monkeypatch):
    _with_lbracket_wall_mount_keepout(monkeypatch, 10.0)
    from packages.truth_plane.validate import validate_geometry
    led = _make([
        ("lbracket", "brk", {"x_mm": 0, "y_mm": 0, "z_mm": 0}, {}),
        ("standoff", "post", {"x_mm": 500, "y_mm": 0, "z_mm": 20}, {}),
    ])
    r = validate_geometry(led)
    assert not any(i.check == "keepout" for i in r.issues), r.summary


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
