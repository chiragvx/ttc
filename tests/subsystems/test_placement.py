"""Phase 1 mate solver (2026-07-19) — packages/subsystems/placement.py + interfaces/connections.

Derives a connected part's world placement from the partner's declared interface frame, instead of the
copilot hand-computing coordinates. The headline test proves it reproduces the hand-verified
BWB+wing placement (the sweep/dihedral offset the LLM used to get wrong)."""

from __future__ import annotations

import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Connection, InterfaceRef, Transform
from packages.subsystems import add_instance, get_subsystem_model
from packages.subsystems.placement import (
    _apply_transform_to_frame,
    _rot_apply,
    connection_issues,
    resolve_placements,
    world_frame_for_interface,
)
from packages.transport.app import make_demo_ledger


def _set(led, iid, name, val, unit="mm", bounds=(-3000.0, 3000.0)):
    led.instances[iid].params[name] = ParameterDef(value=float(val), unit=unit, bounds=bounds)


def _bwb_with_two_wings():
    led = make_demo_ledger()
    led = add_instance(led, "bwb_fuselage", "body")
    _set(led, "body", "span_mm", 500); _set(led, "body", "tip_chord_mm", 130)
    _set(led, "body", "sweep_deg", 15, "deg"); _set(led, "body", "dihedral_deg", 2, "deg")
    led = add_instance(led, "wing_panel", "wr")
    _set(led, "wr", "side_sign", 1, "sign", (-1.0, 1.0)); _set(led, "wr", "root_chord_mm", 130)
    led = add_instance(led, "wing_panel", "wl")
    _set(led, "wl", "side_sign", -1, "sign", (-1.0, 1.0)); _set(led, "wl", "root_chord_mm", 130)
    led.connections = [
        Connection(id="c_r", a=InterfaceRef(instance_id="wr", interface="root"),
                   b=InterfaceRef(instance_id="body", interface="tip_right")),
        Connection(id="c_l", a=InterfaceRef(instance_id="wl", interface="root"),
                   b=InterfaceRef(instance_id="body", interface="tip_left")),
    ]
    return led


def test_interfaces_are_declared():
    assert [i.name for i in get_subsystem_model("bwb_fuselage").interfaces] == ["tip_right", "tip_left"]
    assert [i.name for i in get_subsystem_model("wing_panel").interfaces] == ["root"]


@pytest.mark.parametrize("name", [
    "longeron", "tail_boom", "flat_bar", "wing_spar", "stabilizer_spar", "main_gear_leg", "nose_gear_leg",
])
def test_bar_shaped_subsystems_declare_end_interfaces(name):
    # 2026-07-20 — the generic bar_end_interfaces() helper, applied to the shape family confirmed by
    # direct code reading to be a plain bd.Box(length_mm, width_mm, height_mm) centered at the origin.
    assert [i.name for i in get_subsystem_model(name).interfaces] == ["end_a", "end_b"]


@pytest.mark.parametrize("name", [
    "motor_mount_firewall", "avionics_tray", "battery_bay_divider", "battery_strap_mount", "servo_mount_tray",
])
def test_plate_shaped_subsystems_declare_face_interfaces(name):
    # 2026-07-20 — the generic plate_face_interfaces() helper, applied to the render_bracket-derived
    # shape family confirmed by direct code reading to share the identical width/depth/thickness box.
    assert [i.name for i in get_subsystem_model(name).interfaces] == ["top", "bottom"]


def test_enclosure_declares_box_face_interfaces():
    # 2026-07-22 — the generic box_face_interfaces() helper, applied to enclosure's outer box shell
    # (confirmed a plain bd.Box(box_width_mm, box_depth_mm, box_height_mm) centered at the origin).
    assert [i.name for i in get_subsystem_model("enclosure").interfaces] == [
        "left", "right", "front", "back", "bottom", "top"]


def test_lbracket_declares_wall_mount_and_top_interfaces():
    # 2026-07-22 — bespoke (not a shared generic helper, since render_lbracket's shape is asymmetric):
    # wall_mount is the vertical flange's outer face, top is the horizontal flange's outer face.
    assert [i.name for i in get_subsystem_model("lbracket").interfaces] == ["wall_mount", "top"]


def test_lbracket_mates_cleanly_to_the_enclosures_right_face():
    # This is the fix for the antenna-bracket root cause: lbracket's wall_mount (fixed -X normal) is
    # anti-parallel to enclosure's right face (+X normal) — the ONE clean, rotation-free mate. "box" <
    # "brk" alphabetically, so "box" is the datum at the origin (see placement.py's datum-selection
    # rule) and "brk" derives relative to it.
    led = make_demo_ledger()
    led = add_instance(led, "enclosure", "box")   # box_width_mm=80 default -> right face at x=40
    led = add_instance(led, "lbracket", "brk")    # leg_a_mm=40 default -> wall_mount at local z=20
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="brk", interface="wall_mount"),
                   b=InterfaceRef(instance_id="box", interface="right")),
    ]
    pl = resolve_placements(led)
    assert pl["box"] == Transform()  # datum at origin
    assert pl["brk"].x_mm == pytest.approx(40.0)
    assert pl["brk"].y_mm == pytest.approx(0.0)
    assert pl["brk"].z_mm == pytest.approx(-20.0)
    assert connection_issues(led) == []


def test_lbracket_mated_to_a_non_matching_enclosure_face_is_flagged_not_silently_wrong():
    # The honest limitation, verified: wall_mount's normal is fixed -X, so mating it to enclosure's
    # "left" face (also -X, i.e. PARALLEL not anti-parallel) still resolves a translation -- but
    # connection_issues() must catch the rotation-needed mismatch rather than reporting it clean.
    led = make_demo_ledger()
    led = add_instance(led, "enclosure", "box")
    led = add_instance(led, "lbracket", "brk")
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="brk", interface="wall_mount"),
                   b=InterfaceRef(instance_id="box", interface="left")),
    ]
    issues = connection_issues(led)
    assert len(issues) == 1
    assert "need a rotation to mate" in issues[0]


def test_two_plate_shaped_parts_mate_face_to_face_via_the_generic_helper():
    # avionics_tray (thickness_mm=2.5) 'top' mates battery_bay_divider (thickness_mm=2.0) 'bottom'.
    # No anchor/root in this component -> datum is min(instance ids) alphabetically: "divider" < "tray"
    # (see placement.py's own datum-selection rule), so "divider" is the datum at the origin and
    # "tray" is derived relative to it, landing at world z = -(1.0 + 1.25) = -2.25.
    led = make_demo_ledger()
    led = add_instance(led, "avionics_tray", "tray")
    led = add_instance(led, "battery_bay_divider", "divider")
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="tray", interface="top"),
                   b=InterfaceRef(instance_id="divider", interface="bottom")),
    ]
    pl = resolve_placements(led)
    assert pl["divider"] == Transform()  # datum at origin (alphabetically first)
    assert pl["tray"].z_mm == pytest.approx(-2.25)
    assert pl["tray"].x_mm == pytest.approx(0.0) and pl["tray"].y_mm == pytest.approx(0.0)
    assert connection_issues(led) == []


def test_two_bar_shaped_parts_mate_end_to_end_via_the_generic_helper():
    # Proves bar_end_interfaces() produces frames the EXISTING solver actually accepts -- not just
    # that the interface list is non-empty. Two longerons (default length_mm=400) joined end-to-end:
    # longeron_a's end_b (local x=+200) mates longeron_b's end_a (local x=-200) with zero rotation
    # (v1 mates are pure translation) -- longeron_b's center should land at world x=400.
    led = make_demo_ledger()
    led = add_instance(led, "longeron", "la")
    led = add_instance(led, "longeron", "lb")
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="la", interface="end_b"),
                   b=InterfaceRef(instance_id="lb", interface="end_a")),
    ]
    pl = resolve_placements(led)
    assert pl["la"] == Transform()  # datum at origin
    assert pl["lb"].x_mm == pytest.approx(400.0)
    assert pl["lb"].y_mm == pytest.approx(0.0) and pl["lb"].z_mm == pytest.approx(0.0)
    assert pl["lb"].rx_deg == 0 and pl["lb"].ry_deg == 0 and pl["lb"].rz_deg == 0
    assert connection_issues(led) == []


def test_mate_solver_reproduces_the_hand_verified_wing_placement():
    # THE Phase 1 proof: the sweep/dihedral offset the copilot used to hand-compute (and get wrong) is
    # now DERIVED from the body's own declared tip frame.
    led = _bwb_with_two_wings()
    pl = resolve_placements(led)
    H = 250.0
    y = H * math.tan(math.radians(15))   # ~67.0
    z = H * math.tan(math.radians(2))    # ~8.7
    assert pl["body"] == Transform()  # datum at origin
    assert pl["wr"].x_mm == pytest.approx(H) and pl["wr"].y_mm == pytest.approx(y) and pl["wr"].z_mm == pytest.approx(z)
    assert pl["wl"].x_mm == pytest.approx(-H) and pl["wl"].y_mm == pytest.approx(y) and pl["wl"].z_mm == pytest.approx(z)
    # v1 mates are rotation-free
    for iid in ("wr", "wl"):
        assert pl[iid].rx_deg == 0 and pl[iid].ry_deg == 0 and pl[iid].rz_deg == 0
    assert connection_issues(led) == []


def test_no_connections_means_no_derived_placements():
    led = add_instance(make_demo_ledger(), "bracket", "b1")
    assert resolve_placements(led) == {}


def test_gap_pushes_the_mate_apart_along_the_normal():
    led = _bwb_with_two_wings()
    led.connections[0].gap_mm = 10.0  # right wing pushed +10mm along the body's +X tip normal
    base = resolve_placements(_bwb_with_two_wings())["wr"].x_mm
    gapped = resolve_placements(led)["wr"].x_mm
    assert gapped == pytest.approx(base + 10.0)


def test_dangling_connection_is_flagged():
    led = _bwb_with_two_wings()
    led.connections.append(Connection(id="bad", a=InterfaceRef(instance_id="wr", interface="root"),
                                      b=InterfaceRef(instance_id="ghost", interface="tip_right")))
    issues = connection_issues(led)
    assert any("ghost" in m and "missing instance" in m for m in issues)


def test_connection_issues_scoped_to_one_instance_ignores_an_unrelated_part():
    """foundations-audit H3, 2026-07-21: connection_issues(ledger, instance_id=...) must not let a
    broken connection on a totally different, unrelated instance block/flag a clean one -- this is the
    same underlying gap that let one part's broken connection block a different part's EXPORT (see
    tests/backend/test_app.py's H3 regression test for the full REST-level version)."""
    led = _bwb_with_two_wings()
    # a dangling connection touching ONLY "wl" (and a nonexistent "ghost" instance) -- "wr" and "body"
    # are not endpoints of it, even though "wr" shares the same connected component via "body".
    led.connections.append(Connection(id="bad", a=InterfaceRef(instance_id="wl", interface="root"),
                                      b=InterfaceRef(instance_id="ghost", interface="tip_left")))

    unscoped = connection_issues(led)
    assert any("ghost" in m for m in unscoped)  # unchanged pre-existing whole-ledger behavior

    wl_issues = connection_issues(led, instance_id="wl")
    assert any("ghost" in m for m in wl_issues)  # wl IS an endpoint of the dangling connection

    wr_issues = connection_issues(led, instance_id="wr")
    assert not any("ghost" in m for m in wr_issues)  # wr is unrelated -- must not see wl's problem

    body_issues = connection_issues(led, instance_id="body")
    assert not any("ghost" in m for m in body_issues)  # body is not an endpoint of the bad connection either


def test_unknown_interface_is_flagged():
    led = _bwb_with_two_wings()
    led.connections.append(Connection(id="bad2", a=InterfaceRef(instance_id="wr", interface="nope"),
                                      b=InterfaceRef(instance_id="body", interface="tip_right")))
    issues = connection_issues(led)
    assert any("nope" in m and "does not declare" in m for m in issues)


def test_over_constrained_connection_is_flagged_not_silently_dropped():
    # ENGINEERING_GRAPH_PLAN.md P1.6: v1 places first-reached-wins, but a SECOND conflicting
    # connection into the same part must be REPORTED, not silently ignored. Mate the right wing to the
    # left tip too — it was already placed by its real connection, so this one can't be satisfied.
    led = _bwb_with_two_wings()
    led.connections.append(Connection(id="conflict", a=InterfaceRef(instance_id="wr", interface="root"),
                                      b=InterfaceRef(instance_id="body", interface="tip_left")))
    issues = connection_issues(led)
    assert any("conflict" in m and "do not meet" in m for m in issues)


def test_rotated_datum_composes_correctly():
    # the #1 solver-math risk: a datum with a non-identity rotation must place its child at the
    # ROTATED tip, not the unrotated one. body tip_right (sweep default) rotated 90deg about Z.
    led = make_demo_ledger()
    led = add_instance(led, "bwb_fuselage", "body")
    _set(led, "body", "span_mm", 500)
    led.instances["body"].transform = Transform(rz_deg=90.0)
    led = add_instance(led, "wing_panel", "wr")
    _set(led, "wr", "side_sign", 1, "sign", (-1.0, 1.0))
    led.connections = [Connection(id="c", a=InterfaceRef(instance_id="wr", interface="root"),
                                  b=InterfaceRef(instance_id="body", interface="tip_right"))]
    from packages.subsystems.base import Frame
    from packages.subsystems.placement import _apply_transform_to_frame, _local_frame
    # expected wing origin = body's tip_right world origin (local frame rotated by rz=90 + no translation)
    tip_local = _local_frame(led, "body", "tip_right")
    tip_world = _apply_transform_to_frame(Transform(rz_deg=90.0), tip_local)
    pl = resolve_placements(led)
    assert pl["wr"].x_mm == pytest.approx(tip_world.origin[0])
    assert pl["wr"].y_mm == pytest.approx(tip_world.origin[1])
    assert pl["wr"].z_mm == pytest.approx(tip_world.origin[2])
    # and it is genuinely NOT the unrotated tip (proves the rotation was actually applied)
    assert pl["wr"].x_mm != pytest.approx(250.0)


def test_rotated_datum_mate_is_flagged_not_silently_wrong():
    # 2026-07-19 adversarial review (HIGH): a datum carrying a rotation makes a locally-anti-parallel
    # mate need a WORLD rotation the v1 solver can't do. The guard must check WORLD normals, so this is
    # FLAGGED (rotation-needed) rather than returning a clean self-check on wrong geometry.
    led = _bwb_with_two_wings()
    led.instances["body"].transform = Transform(rz_deg=90.0)
    issues = connection_issues(led)
    assert any("need a rotation" in m for m in issues), issues


def test_clean_identity_datum_mate_is_not_flagged():
    # the flip side — the real current use case (identity datum) must stay clean, no false positive
    assert connection_issues(_bwb_with_two_wings()) == []


def test_world_frame_for_interface_resolves_an_unconnected_instance():
    # 2026-07-22 -- unlike _world_frame (only resolves instances already in resolve_placements'
    # connected set), world_frame_for_interface must work for a plain, unconnected instance too --
    # this is what the "keepout" self-check needs (a clearance zone regardless of how the instance
    # ended up positioned).
    led = make_demo_ledger()
    led = add_instance(led, "enclosure", "box")
    led.instances["box"].transform = Transform(x_mm=10.0, y_mm=20.0, z_mm=30.0)
    wf = world_frame_for_interface(led, "box", "right")
    assert wf is not None
    assert wf.origin == pytest.approx((50.0, 20.0, 30.0))  # local (40,0,0) [box_width_mm=80/2] + offset
    assert wf.normal == pytest.approx((1.0, 0.0, 0.0))
    assert world_frame_for_interface(led, "box", "no_such_interface") is None
    assert world_frame_for_interface(led, "ghost", "right") is None


def test_world_frame_for_interface_matches_resolve_placements_for_a_connected_instance():
    # Cross-check against the already-verified mate solver numbers (root is at wing_panel's own
    # local origin, so its world origin equals the resolved translation exactly).
    led = _bwb_with_two_wings()
    pl = resolve_placements(led)
    wf = world_frame_for_interface(led, "wr", "root")
    assert wf is not None
    assert wf.origin == pytest.approx((pl["wr"].x_mm, pl["wr"].y_mm, pl["wr"].z_mm))


def test_multiple_anchors_in_one_component_are_flagged():
    # 2026-07-19 review (HIGH): v1 keeps one anchor as datum and mates the rest, silently overriding a
    # second explicit transform — flag it.
    led = make_demo_ledger()
    led = add_instance(led, "bwb_fuselage", "body"); _set(led, "body", "span_mm", 500)
    led.instances["body"].transform = Transform(x_mm=0)
    led = add_instance(led, "wing_panel", "wr"); _set(led, "wr", "side_sign", 1, "sign", (-1.0, 1.0))
    led.instances["wr"].transform = Transform(x_mm=100)  # second anchor
    led.connections = [Connection(id="c", a=InterfaceRef(instance_id="wr", interface="root"),
                                  b=InterfaceRef(instance_id="body", interface="tip_right"))]
    assert any("can only honor one" in m for m in connection_issues(led))


def test_self_loop_connection_is_flagged():
    # 2026-07-19 review (LOW): a connection with the same instance on both ends is meaningless.
    led = add_instance(make_demo_ledger(), "wing_panel", "w")
    _set(led, "w", "side_sign", 1, "sign", (-1.0, 1.0))
    led.connections = [Connection(id="s", a=InterfaceRef(instance_id="w", interface="root"),
                                  b=InterfaceRef(instance_id="w", interface="root"))]
    assert any("cannot connect to itself" in m for m in connection_issues(led))


def test_cycle_and_self_loop_do_not_hang_or_crash():
    led = _bwb_with_two_wings()
    led.connections.append(Connection(id="cyc", a=InterfaceRef(instance_id="wr", interface="root"),
                                      b=InterfaceRef(instance_id="wl", interface="root")))
    resolve_placements(led)  # must not hang
    led2 = add_instance(make_demo_ledger(), "wing_panel", "w")
    _set(led2, "w", "side_sign", 1, "sign", (-1.0, 1.0))
    led2.connections = [Connection(id="s", a=InterfaceRef(instance_id="w", interface="root"),
                                   b=InterfaceRef(instance_id="w", interface="root"))]
    resolve_placements(led2)  # self-loop must not crash


def test_rot_apply_matches_build123d_convention():
    # guards the one piece of real 3D math against the empirically-verified Rx·Ry·Rz convention
    assert _rot_apply(0, 0, 90, (1, 0, 0)) == pytest.approx((0, 1, 0))
    assert _rot_apply(90, 0, 0, (0, 1, 0)) == pytest.approx((0, 0, 1))
    assert _rot_apply(90, 90, 0, (1, 0, 0)) == pytest.approx((0, 1, 0))  # the composed-order check


def test_apply_transform_to_frame_translates_and_rotates():
    from packages.subsystems.base import Frame
    f = Frame(origin=(1, 0, 0), normal=(1, 0, 0))
    # pure translation
    w = _apply_transform_to_frame(Transform(x_mm=10, y_mm=5, z_mm=0), f)
    assert w.origin == pytest.approx((11, 5, 0)) and w.normal == pytest.approx((1, 0, 0))
    # rotation rotates both origin and normal
    w2 = _apply_transform_to_frame(Transform(rz_deg=90), f)
    assert w2.origin == pytest.approx((0, 1, 0)) and w2.normal == pytest.approx((0, 1, 0))
