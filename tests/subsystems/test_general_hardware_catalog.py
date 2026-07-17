"""Bulk regression coverage for the 2026-07-17 general (non-aerospace) hardware catalog expansion
(121 subsystems from build-plan/reference/SUBSYSTEM_PROPOSALS.md, generated from 14 archetypes -- the
10 already proven by the UAV catalog expansion plus 4 new ones this batch needed: puck/stepped/
flanged/wedge/plate_bore, each prototyped against real build123d before being committed).

Same "one parametrized file, not 121 separate ones" reasoning as
test_uav_hardware_catalog.py -- see that file's own docstring."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None

CATALOG_NAMES = [
    # Category 1: Fasteners & receiving hardware
    "wing_nut", "cap_nut", "T_nut", "slot_nut", "knurled_nut", "dome_nut", "hex_bolt_blank",
    "socket_cap_bolt_blank", "button_head_bolt_blank", "flat_head_bolt_blank", "thumb_screw",
    "set_screw_pocket", "press_fit_boss", "cotter_pin_slot", "fender_washer", "keyhole_slot_plate",
    "cable_tie_anchor",
    # Category 2: Brackets & mounts
    "cbracket", "u_mounting_bracket", "corner_bracket_gusseted", "gusset_plate", "floor_flange",
    "wall_mount_plate", "hook_bracket", "foot_mount", "cable_clip", "pipe_saddle", "mic_clip",
    "camera_mount_plate", "nema17_face_mount", "nema23_face_mount", "servo_bracket", "hinge",
    "hinge_with_pin", "door_stop",
    # Category 3: Enclosures & covers
    "hinged_box", "sliding_lid_box", "split_shell_case", "snap_fit_box", "stackable_bin",
    "junction_box", "endcap_round", "endcap_square", "threaded_endcap_blank", "cable_gland_boss",
    "bezel_display", "LCD_16x2_bezel",
    # Category 4: Panels & plates
    "blank_plate", "perforated_plate", "breakout_plate", "keystone_plate", "terminal_strip_plate",
    "handle_plate", "label_plate", "pcb_carrier",
    # Category 5: Structural sections
    "round_tube", "rectangular_tube", "round_bar", "i_beam", "angle_iron", "c_channel",
    "extrusion_2020_blank", "extrusion_2040_blank", "frame_corner_bracket",
    # Category 6: Spacers & standoffs
    "stepped_spacer", "tapered_shim", "flat_shim",
    # Category 7: Rotational & transmission
    "flange_collar", "pulley_blank_v", "pulley_blank_flat", "pulley_blank_timing", "sprocket_blank",
    "gear_blank", "pinion_blank", "wheel_blank", "castor_blank", "rigid_coupling", "jaw_coupling",
    "flex_coupling_blank",
    # Category 8: Bearings / bushings / linear
    "sleeve_bushing", "flanged_bushing", "thrust_washer", "pillow_block_housing",
    "flange_bearing_housing", "linear_bearing_block", "lm_rail_end_cap",
    # Category 9: Alignment, locating, jigs
    "locating_pin", "taper_pin", "keyway_shaft", "v_block", "parallel_block_pair", "jig_plate",
    "drill_jig", "alignment_fork",
    # Category 10: Sealing
    "flat_gasket", "oring_boss", "oring_groove_plate", "cable_gland_body",
    # Category 11: Handles, knobs, ergonomic
    "round_knob", "star_knob", "hex_knob", "T_handle", "cabinet_pull", "bar_pull",
    "cylindrical_grip", "tapered_grip",
    # Category 12: Cable, wire, plumbing
    "wire_clip", "zip_tie_saddle", "cable_gland_flange", "strain_relief", "wire_labeler", "hose_barb",
    # Category 13: Assemblies / composites
    "tri_stand", "four_leg_stand", "motor_bracket_stack", "pillow_block_pair_on_rail",
    "hinged_box_with_stop", "sensor_mount_pair", "clamp_two_halves", "flanged_socket_and_peg",
    "bearing_block_and_cap",
]


def test_catalog_size_and_no_duplicates():
    assert len(CATALOG_NAMES) == 121
    assert len(set(CATALOG_NAMES)) == 121, "duplicate name in CATALOG_NAMES"


def test_every_catalog_name_is_registered():
    missing = [n for n in CATALOG_NAMES if n not in SUBSYSTEM_REGISTRY]
    assert missing == [], f"registered under a different name or not wired into __init__.py: {missing}"


def test_no_collision_with_the_pre_existing_catalogs():
    # The original 32-part catalog + the 2026-07-16 UAV 111-item expansion must not have been
    # silently overwritten by this second expansion, and the registry must be exactly
    # (everything before this file) + (this file's own 121) -- no accidental double-registration.
    pre_existing_sample = {
        "bracket", "enclosure", "standoff", "lbracket", "uchannel", "panel", "washer", "table",
        "flat_bar", "square_tube", "dowel_pin", "cover_plate", "t_bar", "z_bracket",
        "mounting_plate_grid", "shaft_collar", "hub", "threaded_boss", "motor_mount", "hex_nut",
        "hex_bar", "hex_standoff", "standoff_frame", "round_post", "saddle_clamp", "lofted_spindle",
        "lofted_hull", "naca_wing", "ogive_fuselage", "winged_fuselage", "bulkhead_frame", "longeron",
        # a handful of the 2026-07-16 UAV expansion's own names, enough to catch a silent overwrite
        # without importing that test module as a package (tests/ has no __init__.py)
        "fin_root_fitting", "wheel_hub", "battery_tray", "stabilizer_spar", "tie_down_ring",
    }
    assert pre_existing_sample & set(CATALOG_NAMES) == set()
    assert pre_existing_sample <= set(SUBSYSTEM_REGISTRY)
    # >= not == : other test files (test_assembly_template.py, test_saddle_clamp.py) register their
    # own throwaway test subsystems into this SAME shared global registry when the full suite runs
    # together, legitimately inflating the count beyond the three catalogs' own 32+111+121 -- what
    # actually matters is that nothing got silently OVERWRITTEN (a real collision would shrink this
    # below the expected floor, never grow it).
    assert len(SUBSYSTEM_REGISTRY) >= 32 + 111 + len(CATALOG_NAMES), (
        f"expected at least 32 (original) + 111 (UAV) + {len(CATALOG_NAMES)} (this batch) = "
        f"{32 + 111 + len(CATALOG_NAMES)} registered subsystems, got {len(SUBSYSTEM_REGISTRY)}"
    )


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
