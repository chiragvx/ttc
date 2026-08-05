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
    resolve_mesh_mate,
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


@pytest.mark.parametrize("name", ["round_post", "round_bar"])
def test_cylinder_shaped_subsystems_declare_end_interfaces(name):
    # 2026-07-27 -- the generic cylinder_end_interfaces() helper (the missing complement to
    # bar_end_interfaces for the round-cross-section family), applied to the shape family confirmed
    # by direct code reading to be a plain bd.Cylinder(radius=dia_mm/2, height=height_mm) centered at
    # the origin, standing along local Z BY DEFAULT (no rotation needed, unlike the box-bar family).
    assert [i.name for i in get_subsystem_model(name).interfaces] == ["bottom", "top"]


def test_two_round_posts_stack_end_to_end_via_the_generic_cylinder_helper():
    # round_post "a" (height_mm=60 default) stacked on round_post "b" (height_mm=60 default) via
    # a.bottom <-> b.top. "a" < "b" alphabetically, so "a" is the datum at the origin.
    led = make_demo_ledger()
    led = add_instance(led, "round_post", "a")
    led = add_instance(led, "round_post", "b")
    led.connections = [
        Connection(id="c1", a=InterfaceRef(instance_id="a", interface="bottom"),
                   b=InterfaceRef(instance_id="b", interface="top")),
    ]
    pl = resolve_placements(led)
    assert pl["a"] == Transform()  # datum at origin
    assert pl["b"].z_mm == pytest.approx(-60.0)  # a's bottom (-30) meets b's top, b's own center 60 below
    assert connection_issues(led) == []


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


# ---------------------------------------------------------------------------------------------------
# Mesh-kind (gear pitch-circle) mating (2026-08-04) -- Frame.radius + cylinder_axis_mesh_interface
# (base.py) + resolve_mesh_mate (placement.py). No real catalog subsystem declares a "mesh" interface
# yet (that adoption -- e.g. gear_blank/pinion_blank/sprocket_blank -- is an explicit follow-up, out of
# this session's owned-file scope), so the mesh-mate tests below use synthetic Subsystem models
# monkeypatched into get_subsystem_model, the SAME technique tests/subsystems/test_fit.py already uses
# for compute_fit's own unit coverage.
# ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,iface", [
    ("round_post", "bottom"), ("round_post", "top"),
    ("longeron", "end_a"), ("longeron", "end_b"),
    ("avionics_tray", "top"), ("avionics_tray", "bottom"),
    ("enclosure", "right"), ("enclosure", "top"),
    ("lbracket", "wall_mount"), ("lbracket", "top"),
])
def test_frame_radius_defaults_to_none_for_every_existing_interface_helper(name, iface):
    # 2026-08-04: Frame.radius is a NEW field, added ONLY for kind="mesh" interfaces. Every
    # pre-existing InterfaceSpec across the catalog (cylinder/bar/plate/box/lbracket shape families --
    # every existing interface-helper family in base.py) must keep producing radius=None: explicit
    # proof of ZERO behavior change for the 86 existing InterfaceSpec(...) call sites.
    from packages.subsystems.placement import _local_frame
    led = add_instance(make_demo_ledger(), name, "x")
    frame = _local_frame(led, "x", iface)
    assert frame is not None
    assert frame.radius is None


def test_cylinder_axis_mesh_interface_declares_a_mesh_kind_pitch_frame_at_the_local_origin():
    # the new interface helper, unit-tested directly against a synthetic Subsystem.
    from packages.subsystems.base import Namespace, ParamSpec, Subsystem, cylinder_axis_mesh_interface
    gear = Subsystem(
        name="_test_mesh_gear", description="", fragment="", disciplines=(),
        params=[ParamSpec("dia_mm", value=40.0, min=5.0, max=200.0, unit="mm")],
        interfaces=[cylinder_axis_mesh_interface("dia_mm")],
    )
    spec = gear.interfaces[0]
    assert spec.name == "mesh"
    assert spec.kind == "mesh"
    ns = Namespace({"dia_mm": ParameterDef(value=40.0, unit="mm", bounds=(5.0, 200.0))})
    frame = spec.frame(ns)
    assert frame.origin == (0.0, 0.0, 0.0)
    assert frame.normal == (0.0, 0.0, 1.0)
    assert frame.radius == pytest.approx(20.0)  # half of dia_mm=40, hand-computed


def test_cylinder_axis_mesh_interface_accepts_a_custom_name():
    from packages.subsystems.base import ParamSpec, Subsystem, cylinder_axis_mesh_interface
    gear = Subsystem(
        name="_test_mesh_gear2", description="", fragment="", disciplines=(),
        params=[ParamSpec("dia_mm", value=10.0, min=1.0, max=100.0, unit="mm")],
        interfaces=[cylinder_axis_mesh_interface("dia_mm", name="pitch")],
    )
    assert gear.interfaces[0].name == "pitch"


def _mesh_gear_model():
    from packages.subsystems.base import ParamSpec, Subsystem, cylinder_axis_mesh_interface
    return Subsystem(
        name="_synthetic_mesh_gear", description="", fragment="", disciplines=(),
        params=[ParamSpec("dia_mm", value=1.0, min=0.1, max=1000.0, unit="mm")],
        interfaces=[cylinder_axis_mesh_interface("dia_mm")],
    )


def _mount_kind_model():
    # an ordinary kind="mount" interface (no radius) -- for the kind-mismatch refusal test.
    from packages.subsystems.base import Frame, InterfaceSpec, Subsystem
    return Subsystem(
        name="_synthetic_mount_thing", description="", fragment="", disciplines=(), params=[],
        interfaces=[InterfaceSpec(name="face", kind="mount", frame=lambda p: Frame(origin=(0.0, 0.0, 0.0)))],
    )


def _synthetic_mesh_registry(monkeypatch, subsystems):
    def fake_get_subsystem_model(name):
        if name not in subsystems:
            raise KeyError(name)
        return subsystems[name]
    # placement.py imports get_subsystem_model at MODULE level (`from packages.subsystems import
    # get_subsystem_model`), unlike fit.py's own lazy per-call import -- so the patch target is
    # placement's own bound name, not packages.subsystems' original one.
    monkeypatch.setattr("packages.subsystems.placement.get_subsystem_model", fake_get_subsystem_model)


def _mesh_ledger(dia_a: float, dia_b: float, type_a="_synthetic_mesh_gear", type_b="_synthetic_mesh_gear"):
    from packages.ledger.schema import Instance
    led = make_demo_ledger()
    return led.model_copy(update={"instances": {
        "ga": Instance(id="ga", subsystem_type=type_a,
                       params={"dia_mm": ParameterDef(value=dia_a, unit="mm", bounds=(0.1, 1000.0))}),
        "gb": Instance(id="gb", subsystem_type=type_b,
                       params={"dia_mm": ParameterDef(value=dia_b, unit="mm", bounds=(0.1, 1000.0))}),
    }})


def test_resolve_mesh_mate_places_the_second_gear_at_the_hand_computed_center_distance(monkeypatch):
    # radius_a = 40/2 = 20mm, radius_b = 60/2 = 30mm -> center_distance = 20 + 30 = 50mm (hand-computed
    # by hand from the cited formula, BEFORE running the code).
    _synthetic_mesh_registry(monkeypatch, {"_synthetic_mesh_gear": _mesh_gear_model()})
    led = _mesh_ledger(40.0, 60.0)
    result = resolve_mesh_mate(led, InterfaceRef(instance_id="ga", interface="mesh"),
                                InterfaceRef(instance_id="gb", interface="mesh"))
    assert result.ok, result.reason
    assert result.center_distance_mm == pytest.approx(50.0)
    # v1: second gear placed along world +X, same Z as the first (in the plane perpendicular to Z)
    assert result.transform.x_mm == pytest.approx(50.0)
    assert result.transform.y_mm == pytest.approx(0.0)
    assert result.transform.z_mm == pytest.approx(0.0)


def test_resolve_mesh_mate_composes_with_the_first_gears_own_placement(monkeypatch):
    # the first gear ("ga") carries its own explicit world transform -- the second gear's computed
    # position must be relative to THAT placement, not the origin. radius_a = radius_b = 10mm ->
    # center_distance = 20mm (hand-computed).
    _synthetic_mesh_registry(monkeypatch, {"_synthetic_mesh_gear": _mesh_gear_model()})
    led = _mesh_ledger(20.0, 20.0)
    led.instances["ga"].transform = Transform(x_mm=5.0, y_mm=7.0, z_mm=3.0)
    result = resolve_mesh_mate(led, InterfaceRef(instance_id="ga", interface="mesh"),
                                InterfaceRef(instance_id="gb", interface="mesh"))
    assert result.ok, result.reason
    assert result.center_distance_mm == pytest.approx(20.0)
    assert result.transform.x_mm == pytest.approx(25.0)  # 5 + 20
    assert result.transform.y_mm == pytest.approx(7.0)
    assert result.transform.z_mm == pytest.approx(3.0)


def test_resolve_mesh_mate_refuses_a_mount_kind_vs_mesh_kind_connection(monkeypatch):
    _synthetic_mesh_registry(monkeypatch, {
        "_synthetic_mesh_gear": _mesh_gear_model(), "_synthetic_mount_thing": _mount_kind_model(),
    })
    led = _mesh_ledger(40.0, 40.0, type_b="_synthetic_mount_thing")
    result = resolve_mesh_mate(led, InterfaceRef(instance_id="ga", interface="mesh"),
                                InterfaceRef(instance_id="gb", interface="face"))
    assert not result.ok
    assert result.transform is None
    assert "kind='mesh'" in result.reason
    assert "mount" in result.reason


def test_resolve_mesh_mate_refuses_a_missing_radius(monkeypatch):
    # both sides ARE kind="mesh", but one never had a radius resolved (Frame.radius stayed None) --
    # the same never-coerce discipline as the kind mismatch above, tested separately.
    from packages.subsystems.base import Frame, InterfaceSpec, Subsystem
    no_radius_gear = Subsystem(
        name="_synthetic_mesh_no_radius", description="", fragment="", disciplines=(), params=[],
        interfaces=[InterfaceSpec(name="mesh", kind="mesh",
                                  frame=lambda p: Frame(origin=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0)))],
    )
    _synthetic_mesh_registry(monkeypatch, {
        "_synthetic_mesh_gear": _mesh_gear_model(), "_synthetic_mesh_no_radius": no_radius_gear,
    })
    led = _mesh_ledger(40.0, 40.0, type_b="_synthetic_mesh_no_radius")
    result = resolve_mesh_mate(led, InterfaceRef(instance_id="ga", interface="mesh"),
                                InterfaceRef(instance_id="gb", interface="mesh"))
    assert not result.ok
    assert result.transform is None
    assert "pitch radius" in result.reason


def test_resolve_mesh_mate_reports_a_missing_instance_or_interface(monkeypatch):
    _synthetic_mesh_registry(monkeypatch, {"_synthetic_mesh_gear": _mesh_gear_model()})
    led = _mesh_ledger(40.0, 40.0)
    missing_instance = resolve_mesh_mate(led, InterfaceRef(instance_id="ghost", interface="mesh"),
                                          InterfaceRef(instance_id="gb", interface="mesh"))
    assert not missing_instance.ok
    assert "does not exist" in missing_instance.reason
    missing_iface = resolve_mesh_mate(led, InterfaceRef(instance_id="ga", interface="nope"),
                                       InterfaceRef(instance_id="gb", interface="mesh"))
    assert not missing_iface.ok
    assert "does not exist" in missing_iface.reason


def test_resolve_placements_dispatches_a_mesh_connection_to_the_center_distance_math(monkeypatch):
    # 2026-08-04 regression: `resolve_mesh_mate` was fully built and unit-tested (the tests directly
    # above), but `resolve_placements` -- the ONLY function the real pipeline actually calls
    # (packages/subsystems/assembly.py's auto-layout) -- never dispatched to it. A plain `Connection`
    # between two kind="mesh" interfaces went through the ordinary coincidence-mate math instead,
    # silently placing both gear centers on top of each other (center_distance=0) rather than
    # radius_a+radius_b apart. This test goes through `resolve_placements` itself (not
    # `resolve_mesh_mate` directly, like every test above it) so this exact gap can't reopen unnoticed.
    _synthetic_mesh_registry(monkeypatch, {"_synthetic_mesh_gear": _mesh_gear_model()})
    led = _mesh_ledger(40.0, 60.0)  # radius_a=20, radius_b=30 -> center_distance=50 (hand-computed)
    led.instances["ga"].transform = Transform(x_mm=0.0, y_mm=0.0, z_mm=0.0)
    led = led.model_copy(update={"connections": [
        Connection(id="c1", a=InterfaceRef(instance_id="ga", interface="mesh"),
                   b=InterfaceRef(instance_id="gb", interface="mesh")),
    ]})
    placements = resolve_placements(led)
    assert placements["ga"].x_mm == pytest.approx(0.0)
    assert placements["gb"].x_mm == pytest.approx(50.0)
    assert placements["gb"].y_mm == pytest.approx(0.0)
    assert placements["gb"].z_mm == pytest.approx(0.0)
