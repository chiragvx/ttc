"""Bulk regression coverage for the 2026-07-16 UAV hardware catalog expansion (111 subsystems from
build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md, generated from 10 proven archetypes -- render_bracket/
render_panel/render_lbracket/render_standoff/render_uchannel/render_bulkhead_frame, or the plain-Box/
hollow-tube/cradle/enclosure-shell inline patterns).

One parametrized test file, not 111 separate ones -- at this scale (111 near-identical-shaped items
sharing 10 already-tested archetypes), a per-item test file would be pure duplication; what's actually
worth asserting per item is registration + the FULL real ledger-integration path (seed -> invariants ->
geometry -> volume), exercised through the SAME `seeded`/`check_invariants`/`geometry_builder`/
`volume_mm3` path the app itself uses -- not a shortcut Namespace construction."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None

CATALOG_NAMES = [
    # Category 1: Fuselage / airframe structure
    "fuselage_ring_frame", "stringer", "keel_beam", "nose_ring", "tail_cone_ring",
    "skin_attach_frame", "doubler_plate", "access_hatch_frame", "canopy_frame", "tail_boom",
    "tail_boom_clamp",
    # Category 2: Wing structure
    "wing_spar", "wing_root_fitting", "wing_tip_fitting", "wing_fold_hinge", "wing_strut",
    "dihedral_brace", "spar_joiner_sleeve", "wing_bolt_pair", "wing_tube_joiner",
    # Category 3: Tail structure
    "stabilizer_spar", "elevator_hinge_bracket", "rudder_hinge_bracket", "tail_skid", "fin_root_fitting",
    # Category 4: Landing gear
    "main_gear_leg", "nose_gear_leg", "gear_mount_plate", "wheel_hub", "wheel_axle", "skid_pad",
    "tailwheel_bracket", "shock_strut_housing", "gear_door_hinge", "jack_point", "tie_down_ring",
    # Category 5: Propulsion mounting hardware
    "motor_mount_firewall", "engine_bed_rail", "nacelle_ring", "cowl_mount_bracket", "prop_hub_blank",
    "prop_spacer", "spinner_backplate", "fuel_tank_tray", "fuel_tank_strap_mount", "exhaust_mount_bracket",
    # Category 6: Payload / avionics bay
    "avionics_tray", "equipment_rack_rail", "camera_mount_static", "sensor_pod_shell",
    "payload_bay_door", "payload_bay_ring", "pcb_stack_rail", "wiring_channel",
    "cable_passthrough_boss", "component_shelf_bracket",
    # Category 7: Power / battery
    "battery_tray", "battery_strap_mount", "battery_hatch", "power_distribution_mount_plate",
    "fuse_holder_bracket", "battery_bay_divider", "esc_mount_plate", "charge_port_bezel",
    # Category 8: Control-surface linkage hardware
    "control_horn", "pushrod_guide", "servo_mount_tray", "hinge_line_bracket",
    "bellcrank_mount_plate", "servo_arm_blank", "linkage_clevis", "control_rod_coupler",
    # Category 9: Antenna / comms / GPS
    "antenna_mount_plate", "patch_antenna_mount", "whip_antenna_base", "gps_mast",
    "comms_bay_bracket", "telemetry_module_tray", "rf_shield_mount", "coax_clamp",
    # Category 10: Deployment / recovery
    "deployment_hinge", "parachute_bay_hatch", "tail_fold_joint", "breakaway_joint_plate",
    "recovery_harness_anchor", "deployment_bay_door", "separation_ring",
    # Category 11: Ground handling / launch
    "launch_rail_shoe", "catapult_hook", "ground_dolly_mount", "wingtip_stand", "handling_handle",
    # Category 12: CubeSat / small-sat specific
    "cubesat_rail", "deck_plate", "kill_switch_mount", "pcb_stack_standoff",
    "solar_panel_backing_plate", "rail_clip", "corner_bumper",
    # Category 13: Fasteners / joinery specific to airframes
    "quick_release_pin", "snap_pin", "turnbuckle_blank", "tensioner_bracket", "glue_tab",
    "rivet_pattern_plate",
    # Category 14: Misc / general airframe hardware
    "inspection_cover", "ballast_tray", "cg_adjustment_rail", "fairing_ring", "bulkhead_ring",
    "data_port_bezel",
]


def test_catalog_size_and_no_duplicates():
    assert len(CATALOG_NAMES) == 111
    assert len(set(CATALOG_NAMES)) == 111, "duplicate name in CATALOG_NAMES"


def test_every_catalog_name_is_registered():
    missing = [n for n in CATALOG_NAMES if n not in SUBSYSTEM_REGISTRY]
    assert missing == [], f"registered under a different name or not wired into __init__.py: {missing}"


def test_no_collision_with_the_pre_existing_catalog():
    # The 32-part pre-existing catalog + the 2 already-built aerospace structural members
    # (bulkhead_frame, longeron) must not have been silently overwritten by this expansion.
    pre_existing = {
        "bracket", "enclosure", "standoff", "lbracket", "uchannel", "panel", "washer", "table",
        "flat_bar", "square_tube", "dowel_pin", "cover_plate", "t_bar", "z_bracket",
        "mounting_plate_grid", "shaft_collar", "hub", "threaded_boss", "motor_mount", "hex_nut",
        "hex_bar", "hex_standoff", "standoff_frame", "round_post", "saddle_clamp", "lofted_spindle",
        "lofted_hull", "naca_wing", "ogive_fuselage", "winged_fuselage", "bulkhead_frame", "longeron",
    }
    assert pre_existing & set(CATALOG_NAMES) == set()
    assert pre_existing <= set(SUBSYSTEM_REGISTRY)


@pytest.mark.parametrize("name", CATALOG_NAMES)
def test_invariants_ok_at_defaults(name, base_ledger, seeded):
    led = seeded(base_ledger, name)
    reasons = get_subsystem(name).check_invariants(led)
    assert reasons == [], f"{name}'s own seeded defaults must satisfy its own invariants: {reasons}"


@pytest.mark.parametrize("name", CATALOG_NAMES)
def test_positive_volume_at_defaults(name, base_ledger, seeded):
    led = seeded(base_ledger, name)
    v = get_subsystem(name).volume_mm3(led)
    assert v > 0.0, f"{name} produced non-positive volume at its own defaults"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
@pytest.mark.parametrize("name", CATALOG_NAMES)
def test_geometry_builds_a_single_valid_solid_at_defaults(name, base_ledger, seeded):
    led = seeded(base_ledger, name)
    part = get_subsystem(name).geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid, f"{name} built an invalid solid at defaults"
    assert len(part.solid.solids()) == 1, f"{name} built {len(part.solid.solids())} solids, expected 1"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
@pytest.mark.parametrize("name", CATALOG_NAMES)
def test_closed_form_volume_matches_real_build_within_5pct(name, base_ledger, seeded):
    led = seeded(base_ledger, name)
    sub = get_subsystem(name)
    approx = sub.volume_mm3(led)
    real = sub.geometry_builder(led).solid.volume
    rel_err = abs(approx - real) / real if real else float("inf")
    assert rel_err < 0.05, f"{name}: closed-form {approx:.1f} vs real build {real:.1f} (err {rel_err:.1%})"
