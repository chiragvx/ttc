"""Golden-conversation eval harness — grades the RESULTING GRAPH `stream_chat` produces, never the
prose, never an LLM-as-judge (correctness is exact structural comparison, same discipline this module
has always used).

History: through 2026-08, this module graded 7 Phase-0-era cases against `propose_delta` alone (a
single-parameter delta on the bracket's SKIN/RIB nodes) — and `grade()` was only ever invoked in tests
against a STUB provider, never a real one. The path that ACTUALLY SHIPS — `stream_chat` ->
instance_ops/connection_ops/coupling_ops/deltas -> the real rules validator -> the resulting instance
tree — had ZERO quality coverage; every regression in that path was found by hand, live, one at a
time. `GOLDEN_GRAPH` below (see `packages/agents/eval_graph.py` for the harness machinery) replaces
that Phase-0 set, migrating its CLARIFY-preserving cases rather than deleting them (see the "migrated
from the original 7-case GOLDEN" cases below) and adding coverage for:

  1. NEVER inventing a subsystem_type outside the real SUBSYSTEM_REGISTRY (the one HARD, always-on
     CI gate — see `eval_graph._check_no_invented_subsystem_types`, run on every case, plus the
     dedicated adversarial case + test below).
  2. Correct part types + roughly correct counts for a multi-part decomposition request.
  3. Clarify-vs-guess on genuinely ambiguous asks.
  4. No parameter smuggled directly onto an add_instance op object (recovered into sibling `deltas`).
  5. No turn-level `rationale` key on the top-level proposal object itself (schema-shape; a
     documented live failure that poisons the WHOLE call rather than partially applying).
  6. A newly-added part whose request stated real dimensions/proportions gets sized accordingly.
  7. connection_ops (topology) preferred over a hand-computed position when both interfaces exist.

Design constraints (see the task this responds to):
  - `grade_offline` runs fully OFFLINE against a deterministic injected fake `stream_post` (the exact
    seam `test_openrouter_provider.py` already uses) — no network, no API key. This is what CI gates
    on: since every fixture is hand-authored to represent CORRECT model behavior, a failure here is a
    real regression in `packages.ledger`/`packages.subsystems`, never model non-determinism.
  - `grade_live` OPTIONALLY runs the same cases' `prompt`s against a real model (key-gated behind
    `OPENROUTER_API_KEY`, same posture as `tests/live/test_openrouter_live.py`) and reports an
    accuracy NUMBER — never a hard CI gate; stochastic model quality must never make a build flaky.
"""

from __future__ import annotations

from packages.agents.eval_graph import (
    CaseResult,
    GraphCaseContext,
    GraphEvalCase,
    GraphEvalReport,
    all_of,
    expect_clarify,
    expect_connected,
    expect_delta_applied,
    expect_instance_op_rejected,
    expect_instance_params,
    expect_moved,
    expect_no_hand_computed_position,
    expect_no_new_instances,
    expect_no_proposal_and_error,
    expect_present,
    expect_recovered_smuggled_deltas,
    expect_removed,
    expect_types,
    grade_live,
    grade_offline,
    run_case_live,
    run_case_offline,
)
from packages.ledger.nodes import HOLE_DIA, RIB, SKIN

# ===================================================================================================
# GOLDEN_GRAPH — ~30 hand-authored cases. No real past-session event logs exist on this host to mine
# for fixtures (packages/ledger/events.py is replayable, but nothing is persisted anywhere in this
# repo/checkout to source from) — hand-authoring directly was the pragmatic call here, per the task's
# own "use your judgment" guidance, rather than over-investing in a mining pipeline with no real input.
# ===================================================================================================

GOLDEN_GRAPH: list[GraphEvalCase] = [
    # --- migrated from the original 7-case GOLDEN (Phase 0) — same intents, same expected behavior,
    # now graded through the real stream_chat -> apply pipeline instead of a bare propose_delta stub.
    GraphEvalCase(
        name="clarify_thicken_the_skin",
        prompt="thicken the skin",
        initial_instances=(("bracket", "root"),),
        fixture_tool_call={"request_clarification": "By how much would you like to thicken the skin, "
                                                     "and to what value (mm)?",
                            "suggestions": ["+0.5 mm", "+1 mm", "+2 mm"]},
        check=expect_clarify(),
    ),
    GraphEvalCase(
        name="clarify_make_it_stronger",
        prompt="make it stronger",
        initial_instances=(("bracket", "root"),),
        fixture_tool_call={"request_clarification": "Stronger against what — bending load, more "
                                                     "rib support, thicker skin? And roughly how much?",
                            "suggestions": ["thicker skin", "tighter rib spacing", "bigger plate"]},
        check=expect_clarify(),
    ),
    GraphEvalCase(
        name="clarify_bare_6S",
        prompt="6S",
        fixture_tool_call={"request_clarification": "I'm not sure what part or parameter '6S' refers "
                                                     "to here — could you say what you'd like to change?",
                            "suggestions": []},
        check=expect_clarify(),
    ),
    GraphEvalCase(
        name="clarify_bare_2_inch",
        prompt="2 inch",
        fixture_tool_call={"request_clarification": "2 inches of what, on which part?", "suggestions": []},
        check=expect_clarify(),
    ),
    GraphEvalCase(
        name="skin_3mm_delta",
        prompt="make the skin 3 mm",
        initial_instances=(("bracket", "root"),),
        fixture_tool_call={"deltas": [{"target_node": SKIN, "requested_value": 3.0}]},
        check=expect_delta_applied(SKIN, 3.0),
    ),
    GraphEvalCase(
        name="rib_spacing_25_delta",
        prompt="set rib spacing to 25",
        initial_instances=(("bracket", "root"),),
        fixture_tool_call={"deltas": [{"target_node": RIB, "requested_value": 25.0}]},
        check=expect_delta_applied(RIB, 25.0),
    ),
    GraphEvalCase(
        name="hole_diameter_8mm_delta",
        prompt="make the hole diameter 8mm",
        initial_instances=(("bracket", "root"),),
        fixture_tool_call={"deltas": [{"target_node": HOLE_DIA, "requested_value": 8.0}]},
        check=expect_delta_applied(HOLE_DIA, 8.0),
    ),
    GraphEvalCase(
        name="batch_two_deltas_one_turn",
        prompt="make the skin 3mm and the rib spacing 30mm",
        initial_instances=(("bracket", "root"),),
        fixture_tool_call={"deltas": [{"target_node": SKIN, "requested_value": 3.0},
                                       {"target_node": RIB, "requested_value": 30.0}]},
        check=all_of(expect_delta_applied(SKIN, 3.0), expect_delta_applied(RIB, 30.0)),
    ),

    # --- item 2: single catalog part type -> one instance_ops add (the "even a single type is still
    # instance_ops" rule from _INSTANCE_OPS_SECTION).
    GraphEvalCase(
        name="add_single_bracket",
        prompt="make a bracket",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "bracket", "instance_id": "root"}]},
        check=expect_types(exact={"bracket"}, min_counts={"bracket": 1}),
    ),
    GraphEvalCase(
        name="add_single_standoff",
        prompt="I need a standoff",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "standoff", "instance_id": "standoff_1"}]},
        check=expect_types(exact={"standoff"}, min_counts={"standoff": 1}),
    ),
    GraphEvalCase(
        name="add_two_brackets_counts",
        prompt="give me two brackets",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "bracket", "instance_id": "bracket_1"},
            {"op": "add_instance", "subsystem_type": "bracket", "instance_id": "bracket_2"}]},
        check=expect_types(exact={"bracket"}, min_counts={"bracket": 2}),
    ),

    # --- item 2: multi-part decomposition (the worked examples from prompt_builder.py's own
    # _INSTANCE_OPS_SECTION — chosen so the golden set pins guidance this codebase ALREADY documents
    # as correct, rather than inventing a new decomposition opinion here).
    GraphEvalCase(
        name="satellite_decomposition",
        prompt="design a satellite",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "enclosure", "instance_id": "bus"},
            {"op": "add_instance", "subsystem_type": "round_post", "instance_id": "mast_1"},
            {"op": "add_instance", "subsystem_type": "round_post", "instance_id": "mast_2"},
            {"op": "add_instance", "subsystem_type": "mounting_plate_grid", "instance_id": "payload_deck"},
            {"op": "add_instance", "subsystem_type": "bracket", "instance_id": "mount_1"},
        ]},
        check=expect_types(exact={"enclosure", "round_post", "mounting_plate_grid", "bracket"},
                           min_counts={"enclosure": 1, "round_post": 2, "mounting_plate_grid": 1, "bracket": 1}),
    ),
    GraphEvalCase(
        name="drone_frame_decomposition",
        prompt="a drone frame",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "enclosure", "instance_id": "fc_bay"},
            {"op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "arm_1"},
            {"op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "arm_2"},
            {"op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "arm_3"},
            {"op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "arm_4"},
            {"op": "add_instance", "subsystem_type": "standoff", "instance_id": "motor_mount_1"},
            {"op": "add_instance", "subsystem_type": "standoff", "instance_id": "motor_mount_2"},
            {"op": "add_instance", "subsystem_type": "standoff", "instance_id": "motor_mount_3"},
            {"op": "add_instance", "subsystem_type": "standoff", "instance_id": "motor_mount_4"},
        ]},
        check=expect_types(exact={"enclosure", "flat_bar", "standoff"},
                           min_counts={"enclosure": 1, "flat_bar": 4, "standoff": 4}),
    ),
    GraphEvalCase(
        name="robot_arm_decomposition",
        prompt="a robot arm",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "t_bar", "instance_id": "link_1"},
            {"op": "add_instance", "subsystem_type": "t_bar", "instance_id": "link_2"},
            {"op": "add_instance", "subsystem_type": "t_bar", "instance_id": "link_3"},
            {"op": "add_instance", "subsystem_type": "hub", "instance_id": "joint_1"},
            {"op": "add_instance", "subsystem_type": "hub", "instance_id": "joint_2"},
            {"op": "add_instance", "subsystem_type": "motor_mount", "instance_id": "motor_1"},
        ]},
        check=expect_types(exact={"t_bar", "hub", "motor_mount"},
                           min_counts={"t_bar": 3, "hub": 2, "motor_mount": 1}),
    ),
    GraphEvalCase(
        # 2026-07-19's real "intake manifold" live bug (see _ASSEMBLY_CONNECTIVITY_SECTION's own
        # docstring): a plenum + 4 runners + a mounting flange, none of whose types declare
        # interfaces — pins that the DECOMPOSITION (types/counts) is still correct even though this
        # case's parts can only be auto-laid-out, not connection_ops-mated (contrast the two
        # connection_ops cases further below, where interfaces DO exist).
        name="intake_manifold_decomposition",
        prompt="an intake manifold: a plenum with 4 runner tubes and a mounting flange",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "enclosure", "instance_id": "plenum"},
            {"op": "add_instance", "subsystem_type": "round_tube", "instance_id": "runner_1"},
            {"op": "add_instance", "subsystem_type": "round_tube", "instance_id": "runner_2"},
            {"op": "add_instance", "subsystem_type": "round_tube", "instance_id": "runner_3"},
            {"op": "add_instance", "subsystem_type": "round_tube", "instance_id": "runner_4"},
            {"op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "flange"},
        ]},
        check=expect_types(exact={"enclosure", "round_tube", "flat_bar"},
                           min_counts={"enclosure": 1, "round_tube": 4, "flat_bar": 1}),
    ),

    # --- item 6: a newly-added part sized to what was actually described, never left at generic
    # catalog defaults. "glider_fuselage_sizing" reuses prompt_builder.py's OWN verified worked example
    # verbatim (the same numbers it teaches the model to propose) — pinning that documented guidance
    # actually round-trips through the real apply pipeline, not just existing as prose in a prompt.
    GraphEvalCase(
        name="glider_fuselage_sizing",
        prompt="a slender, ~1.2m long-range glider fuselage, blunt rounded nose, tapering to a fine "
               "point at the tail",
        fixture_tool_call={
            "instance_ops": [
                {"op": "add_instance", "subsystem_type": "lofted_spindle", "instance_id": "fuselage"}],
            "deltas": [
                {"target_node": "instances.fuselage.params.length_mm", "requested_value": 1200.0},
                {"target_node": "instances.fuselage.params.max_width_mm", "requested_value": 120.0},
                {"target_node": "instances.fuselage.params.start_width_mm", "requested_value": 60.0},
                {"target_node": "instances.fuselage.params.start_taper_mm", "requested_value": 150.0},
                {"target_node": "instances.fuselage.params.end_taper_mm", "requested_value": 900.0},
                {"target_node": "instances.fuselage.params.end_width_mm", "requested_value": 8.0},
                {"target_node": "instances.fuselage.params.start_height_mm", "requested_value": 60.0},
                {"target_node": "instances.fuselage.params.end_height_mm", "requested_value": 8.0},
            ],
        },
        check=all_of(
            expect_types(exact={"lofted_spindle"}),
            expect_instance_params("fuselage", {
                "length_mm": 1200.0, "max_width_mm": 120.0, "start_width_mm": 60.0,
                "start_taper_mm": 150.0, "end_taper_mm": 900.0, "end_width_mm": 8.0,
                "start_height_mm": 60.0, "end_height_mm": 8.0,
            }),
        ),
    ),
    GraphEvalCase(
        name="standoff_height_sizing",
        prompt="add a shelf-support standoff about 150mm tall",
        fixture_tool_call={
            "instance_ops": [
                {"op": "add_instance", "subsystem_type": "standoff", "instance_id": "post_1"}],
            "deltas": [{"target_node": "instances.post_1.params.height_mm", "requested_value": 150.0}],
        },
        check=all_of(expect_types(exact={"standoff"}), expect_instance_params("post_1", {"height_mm": 150.0})),
    ),
    GraphEvalCase(
        name="mounting_plate_grid_sizing",
        prompt="a mounting plate grid, 4 columns by 3 rows of holes",
        fixture_tool_call={
            "instance_ops": [
                {"op": "add_instance", "subsystem_type": "mounting_plate_grid", "instance_id": "deck"}],
            "deltas": [
                {"target_node": "instances.deck.params.cols", "requested_value": 4.0},
                {"target_node": "instances.deck.params.rows", "requested_value": 3.0},
            ],
        },
        check=all_of(expect_types(exact={"mounting_plate_grid"}),
                     expect_instance_params("deck", {"cols": 4.0, "rows": 3.0})),
    ),
    GraphEvalCase(
        name="shaft_collar_bore_sizing",
        prompt="a shaft collar to hold a 10mm shaft",
        fixture_tool_call={
            "instance_ops": [
                {"op": "add_instance", "subsystem_type": "shaft_collar", "instance_id": "collar_1"}],
            "deltas": [{"target_node": "instances.collar_1.params.bore_dia_mm", "requested_value": 10.0}],
        },
        check=all_of(expect_types(exact={"shaft_collar"}),
                     expect_instance_params("collar_1", {"bore_dia_mm": 10.0})),
    ),
    GraphEvalCase(
        name="hub_disc_sizing",
        prompt="a hub for a 25mm shaft with a 60mm disc",
        fixture_tool_call={
            "instance_ops": [{"op": "add_instance", "subsystem_type": "hub", "instance_id": "hub_1"}],
            "deltas": [
                {"target_node": "instances.hub_1.params.bore_dia_mm", "requested_value": 25.0},
                {"target_node": "instances.hub_1.params.disc_dia_mm", "requested_value": 60.0},
            ],
        },
        check=all_of(expect_types(exact={"hub"}),
                     expect_instance_params("hub_1", {"bore_dia_mm": 25.0, "disc_dia_mm": 60.0})),
    ),
    GraphEvalCase(
        name="round_post_leg_sizing",
        prompt="a round post standoff-style leg, 12mm diameter, 200mm tall",
        fixture_tool_call={
            "instance_ops": [{"op": "add_instance", "subsystem_type": "round_post", "instance_id": "leg_1"}],
            "deltas": [
                {"target_node": "instances.leg_1.params.dia_mm", "requested_value": 12.0},
                {"target_node": "instances.leg_1.params.height_mm", "requested_value": 200.0},
            ],
        },
        check=all_of(expect_types(exact={"round_post"}),
                     expect_instance_params("leg_1", {"dia_mm": 12.0, "height_mm": 200.0})),
    ),
    GraphEvalCase(
        # assembly-template sizing: add_instance's params get resized via SIBLING deltas exactly like
        # any other subsystem — `table` additionally materializes child instances (flat_bar top +
        # round_post legs) via reconcile_all, exercised here as a side effect, never asserted on
        # directly (item 6 only cares that the master instance itself is sized right).
        name="table_sizing",
        prompt="a table 900mm wide, 600mm deep, standing 750mm tall",
        fixture_tool_call={
            "instance_ops": [{"op": "add_instance", "subsystem_type": "table", "instance_id": "table_1"}],
            "deltas": [
                {"target_node": "instances.table_1.params.top_width_mm", "requested_value": 900.0},
                {"target_node": "instances.table_1.params.top_depth_mm", "requested_value": 600.0},
                {"target_node": "instances.table_1.params.leg_height_mm", "requested_value": 750.0},
            ],
        },
        check=expect_instance_params("table_1", {"top_width_mm": 900.0, "top_depth_mm": 600.0,
                                                  "leg_height_mm": 750.0}),
    ),

    # --- item 7: connection-graph topology used instead of a hand-computed position, whenever both
    # sides declare a matching interface. Both recipes are the SAME ones prompt_builder.py's own
    # _INSTANCE_OPS_SECTION teaches as "verified" -- pinning that guidance actually produces a
    # correctly mate-solved graph, not just plausible-sounding prose.
    GraphEvalCase(
        name="wing_panel_connects_to_bwb_fuselage",
        prompt="add the outer wing panels, continuing the body's own taper",
        initial_instances=(("bwb_fuselage", "body"),),
        fixture_tool_call={
            "instance_ops": [
                {"op": "add_instance", "subsystem_type": "wing_panel", "instance_id": "wing_r"},
                {"op": "add_instance", "subsystem_type": "wing_panel", "instance_id": "wing_l"},
            ],
            "deltas": [
                {"target_node": "instances.wing_r.params.root_chord_mm", "requested_value": 80.0},
                {"target_node": "instances.wing_r.params.thickness_pct", "requested_value": 12.0},
                {"target_node": "instances.wing_r.params.sweep_deg", "requested_value": 25.0},
                {"target_node": "instances.wing_r.params.dihedral_deg", "requested_value": 0.0},
                {"target_node": "instances.wing_r.params.side_sign", "requested_value": 1.0},
                {"target_node": "instances.wing_l.params.root_chord_mm", "requested_value": 80.0},
                {"target_node": "instances.wing_l.params.thickness_pct", "requested_value": 12.0},
                {"target_node": "instances.wing_l.params.sweep_deg", "requested_value": 25.0},
                {"target_node": "instances.wing_l.params.dihedral_deg", "requested_value": 0.0},
                {"target_node": "instances.wing_l.params.side_sign", "requested_value": -1.0},
            ],
            "connection_ops": [
                {"op": "add_connection", "a_instance": "wing_r", "a_interface": "root",
                 "b_instance": "body", "b_interface": "tip_right"},
                {"op": "add_connection", "a_instance": "wing_l", "a_interface": "root",
                 "b_instance": "body", "b_interface": "tip_left"},
            ],
        },
        check=all_of(
            expect_types(exact={"wing_panel"}, min_counts={"wing_panel": 2}),
            expect_no_hand_computed_position("wing_r"),
            expect_no_hand_computed_position("wing_l"),
            expect_connected("wing_r", "root", "body", "tip_right"),
            expect_connected("wing_l", "root", "body", "tip_left"),
        ),
    ),
    GraphEvalCase(
        name="lbracket_connects_to_enclosure_face",
        prompt="bolt an L-bracket flush to the right side of the enclosure",
        initial_instances=(("enclosure", "box"),),
        fixture_tool_call={
            "instance_ops": [
                {"op": "add_instance", "subsystem_type": "lbracket", "instance_id": "brk"}],
            "connection_ops": [
                {"op": "add_connection", "a_instance": "brk", "a_interface": "wall_mount",
                 "b_instance": "box", "b_interface": "right"},
            ],
        },
        check=all_of(
            expect_types(exact={"lbracket"}),
            expect_no_hand_computed_position("brk"),
            expect_connected("brk", "wall_mount", "box", "right"),
        ),
    ),
    # 2026-08-04 -- regression case for a live-observed defect: a chat-driven 2-gear meshing request
    # built as gear_blank (toothless, mount-kind interfaces only) got manually-guessed x/y/z positions
    # that ended up heavily overlapping (no grounded center-distance math exists for gear_blank at
    # all). This case pins the CORRECT path -- spur_gear (kind="mesh" interface, real center-distance
    # solver in packages/subsystems/placement.py::resolve_mesh_mate) wired via connection_ops, never a
    # hand-computed position -- so if that dispatch (fixed the same day this case was added -- see
    # placement.py::resolve_placements) ever regresses, this eval case fails loudly instead of only
    # ever being caught by a user looking at a rendered blueprint again.
    GraphEvalCase(
        name="two_spur_gears_mesh_via_connection_ops_not_hand_computed_position",
        prompt="add a 20-tooth pinion meshing with a 30-tooth gear",
        initial_instances=(),
        fixture_tool_call={
            "instance_ops": [
                {"op": "add_instance", "subsystem_type": "spur_gear", "instance_id": "pinion"},
                {"op": "add_instance", "subsystem_type": "spur_gear", "instance_id": "gear"},
            ],
            "deltas": [
                {"target_node": "instances.pinion.params.tooth_count", "requested_value": 20.0},
                {"target_node": "instances.gear.params.tooth_count", "requested_value": 30.0},
            ],
            "connection_ops": [
                {"op": "add_connection", "a_instance": "pinion", "a_interface": "mesh",
                 "b_instance": "gear", "b_interface": "mesh"},
            ],
        },
        check=all_of(
            expect_types(exact={"spur_gear"}, min_counts={"spur_gear": 2}),
            expect_no_hand_computed_position("pinion"),
            expect_no_hand_computed_position("gear"),
            expect_connected("pinion", "mesh", "gear", "mesh"),
        ),
    ),

    # --- item 4: a dimension smuggled directly onto add_instance (2026-07-27 documented live
    # failure — packages/ledger/deltas.py::DeltaProposal._repair_known_wire_quirks) must be
    # RECOVERED into the sibling `deltas` list, not lost / not left crashing the whole call.
    GraphEvalCase(
        name="smuggled_dims_on_add_instance_are_recovered",
        prompt="add a flat bar, 500mm long, 20mm wide, 5mm thick",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "flat_bar", "instance_id": "bar_1",
             "length_mm": 500.0, "width_mm": 20.0, "thickness_mm": 5.0}]},
        check=all_of(
            expect_types(exact={"flat_bar"}),
            expect_recovered_smuggled_deltas("bar_1", {"length_mm", "width_mm", "thickness_mm"}),
            expect_instance_params("bar_1", {"length_mm": 500.0, "width_mm": 20.0, "thickness_mm": 5.0}),
        ),
    ),

    # --- item 5: a turn-level `rationale` alongside instance_ops (2026-07-26 documented live
    # failure) is NOT a real field on the top-level proposal -- DeltaProposal's extra="forbid"
    # rejects the WHOLE call, including the otherwise-good instance_ops, rather than silently
    # dropping just the bad key. A hard, schema-level regression pin (see the dedicated test in
    # tests/backend/test_agents.py that also asserts "rationale" can never become a real top-level
    # field without this case's expectation changing too).
    GraphEvalCase(
        name="top_level_rationale_poisons_the_whole_call",
        prompt="add a bracket, this is for mounting the electronics",
        fixture_tool_call={
            "instance_ops": [
                {"op": "add_instance", "subsystem_type": "bracket", "instance_id": "brk_2"}],
            "rationale": "building a bracket for mounting",
        },
        check=all_of(expect_no_proposal_and_error("could not be parsed"), expect_no_new_instances()),
    ),

    # --- item 1 (the hard gate): a model that tries to invent a subsystem_type outside the real
    # registry -- "satellite_body" is the EXACT counter-example prompt_builder.py itself names as what
    # must never be invented. The schema layer alone can't catch this (subsystem_type is a plain str),
    # so this pins that the RULES layer (apply_instance_op's known_subsystem_types check) does.
    GraphEvalCase(
        name="invented_subsystem_type_is_rejected_not_silently_created",
        prompt="design a satellite",
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "satellite_body", "instance_id": "body_1"}]},
        check=expect_instance_op_rejected(),
    ),

    # --- item 2 (refinement): adding detail to an EXISTING design must add only the genuinely NEW
    # part, never re-add a duplicate of something already in the file (packages/agents/prompt_builder.py's
    # "REFINING an existing design" guidance).
    GraphEvalCase(
        name="refinement_adds_only_the_new_part",
        prompt="it will also need a mounting bracket for the electronics",
        initial_instances=(("enclosure", "box"),),
        fixture_tool_call={"instance_ops": [
            {"op": "add_instance", "subsystem_type": "bracket", "instance_id": "electronics_bracket"}]},
        check=expect_types(exact={"bracket"}, min_counts={"bracket": 1}),
    ),

    # --- the other two InstanceOp variants (remove/move) — real ops on the SAME shipped path, not
    # otherwise exercised by items 1-7 above.
    GraphEvalCase(
        name="remove_instance_case",
        prompt="actually I don't need the standoff, remove it",
        initial_instances=(("bracket", "root"), ("standoff", "extra")),
        fixture_tool_call={"instance_ops": [{"op": "remove_instance", "instance_id": "extra"}]},
        check=all_of(expect_removed("extra"), expect_present("root")),
    ),
    GraphEvalCase(
        name="move_instance_case",
        prompt="move the enclosure up 50mm",
        initial_instances=(("enclosure", "box"),),
        fixture_tool_call={"instance_ops": [
            {"op": "move_instance", "instance_id": "box", "x_mm": 0.0, "y_mm": 0.0, "z_mm": 50.0}]},
        check=expect_moved("box", 0.0, 0.0, 50.0),
    ),

    # --- item 3 (clarify vs. guess), generalized beyond the migrated bracket-only cases above: the
    # SAME discipline must hold once other part types/contexts are in play, not just the original
    # Phase-0 SKIN/RIB pair.
    GraphEvalCase(
        name="clarify_ambiguous_bigger_on_a_new_part_type",
        prompt="make the enclosure bigger",
        initial_instances=(("enclosure", "box"),),
        fixture_tool_call={"request_clarification": "Bigger in which dimension — width, depth, or "
                                                     "height — and by how much?",
                            "suggestions": ["+20mm width", "+20mm depth", "+20mm height"]},
        check=expect_clarify(),
    ),
    GraphEvalCase(
        name="clarify_ambiguous_more_support",
        prompt="add more support",
        initial_instances=(("bracket", "root"),),
        fixture_tool_call={"request_clarification": "More support how — tighter rib spacing, a "
                                                     "thicker skin, or a wider plate?",
                            "suggestions": ["tighter rib spacing", "thicker skin", "wider plate"]},
        check=expect_clarify(),
    ),
]


def grade(cases: list[GraphEvalCase] = GOLDEN_GRAPH) -> GraphEvalReport:
    """The default, CI-gating entry point: grade `cases` fully offline (see `grade_offline`)."""
    return grade_offline(cases)


__all__ = [
    "GOLDEN_GRAPH",
    "GraphEvalCase",
    "GraphCaseContext",
    "GraphEvalReport",
    "CaseResult",
    "grade",
    "grade_offline",
    "grade_live",
    "run_case_offline",
    "run_case_live",
    "all_of",
    "expect_clarify",
    "expect_connected",
    "expect_delta_applied",
    "expect_instance_op_rejected",
    "expect_instance_params",
    "expect_moved",
    "expect_no_hand_computed_position",
    "expect_no_new_instances",
    "expect_no_proposal_and_error",
    "expect_present",
    "expect_recovered_smuggled_deltas",
    "expect_removed",
    "expect_types",
]
