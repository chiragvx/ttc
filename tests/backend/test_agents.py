"""Runtime agent layer: propose->review->commit session + eval harness (test-only stub provider)."""

from __future__ import annotations

from packages.agents.eval import CLARIFY, EvalCase, grade
from packages.agents.prompt_builder import build_system_prompt, build_system_prompt_from_json
from packages.agents.runtime import CoModelingSession
from packages.ledger.events import EventLog
from packages.ledger.nodes import BUILD_ORIENTATION, OPERATING_TEMP, POWER_DISSIPATION, SKIN, SLIP_FIT
from packages.ledger.parameter import LockState
from packages.ledger.schema import ReviewState
from packages.subsystems import add_instance, get_subsystem
from packages.transport.app import make_demo_ledger

TS = "2026-06-28T00:00:00Z"


def test_session_proposes_then_human_commits(base_ledger, stub_provider):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    session = CoModelingSession(stub_provider, log)

    result = session.propose("make the skin 3 mm", ts=TS)
    assert not result.needs_clarification
    assert result.trial_outcomes[0].status.value == "APPLIED"
    # proposal is NOT yet committed -> fold still shows the original value
    assert log.fold().instances["root"].params["skin_thickness_mm"].value == 2.0

    session.accept(result.proposal.deltas[0], ts=TS)            # human accepts
    assert log.fold().instances["root"].params["skin_thickness_mm"].value == 3.0
    assert log.fold().review.state is ReviewState.AI_PROPOSED   # still needs sign-off

    session.signoff("pe@example.com", ts=TS)
    assert log.fold().review.state is ReviewState.ENGINEER_REVIEWED


def test_clarification_proposal_commits_nothing(base_ledger, stub_provider):
    log = EventLog()
    log.append_genesis(base_ledger, actor="system", ts=TS)
    session = CoModelingSession(stub_provider, log)
    result = session.propose("make it better somehow", ts=TS)
    assert result.needs_clarification
    assert not result.proposal.deltas
    assert SKIN  # node constant import sanity


def test_system_prompt_teaches_feature_ops_cutting_capability(base_ledger):
    # any part can have a hole/pocket/slot cut into it via feature_ops — the copilot must never be
    # left to conclude a part "doesn't support" a cutout (that used to be a dead-end response).
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "feature_ops" in prompt
    assert "hole" in prompt.lower() and "pocket" in prompt.lower() and "slot" in prompt.lower()
    assert "through=true" in prompt or "through" in prompt.lower()
    # guidance must explicitly disclaim the old dead-end phrasing
    assert "doesn't support" in prompt and "cutout" in prompt
    # the copilot needs a real instance id to target feature_ops at (never invent one) — the instance
    # tree must be listed in the prompt for this to be possible
    assert "Current instances" in prompt and "`root`" in prompt and "bracket" in prompt


def test_system_prompt_teaches_instance_ops_assembly_composition(base_ledger):
    # a request for something that ISN'T a single catalog part type (a satellite, a drone frame, ...)
    # must not be a dead-end refusal — the copilot should be taught to decompose it into instance_ops
    # over EXISTING registered subsystem types instead.
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "instance_ops" in prompt
    # the worked satellite-decomposition example, built only from real registered subsystem names
    assert "satellite" in prompt.lower()
    assert "enclosure" in prompt and "round_post" in prompt and "mounting_plate_grid" in prompt
    # explicit that subsystem_type must be a real registered name, never invented (the prompt names
    # "satellite_body" only as the counter-example of what NOT to invent)
    assert "never invent" in prompt.lower()
    assert "do not" in prompt.lower() or "never" in prompt.lower()
    # explicit that position can be omitted and auto-layout applies
    assert "auto-layout" in prompt.lower() or "auto layout" in prompt.lower()
    # honest disclaimer: this is generic structural composition, not real aerospace/orbital domain knowledge
    assert "orbital" in prompt.lower() or "thermal" in prompt.lower()


def test_system_prompt_grounds_first_time_subsystem_param_names():
    # Confirmed live bug: the first time EVER a subsystem type is added to a file, the model had zero
    # grounding in its real param names (they only appear in the "Tunable parameters" section once a
    # real instance already exists — see _all_geometry_paths) and blind-guessed plausible-sounding
    # but WRONG names (e.g. `fuselage_length_mm` instead of the real `length_mm`). An EMPTY ledger
    # (no instances at all) must still teach every subsystem's real catalog param names up front.
    empty_ledger = make_demo_ledger()
    assert not empty_ledger.instances
    prompt = build_system_prompt(None, empty_ledger)

    # the REAL winged_fuselage param names (packages/subsystems/winged_fuselage.py ParamSpec list) —
    # no wall_thickness_mm: ogive_fuselage (and by extension winged_fuselage) is a SOLID body
    for real_name in (
        "length_mm", "max_width_mm", "max_height_mm", "start_taper_mm", "end_taper_mm",
        "start_width_mm", "start_height_mm", "end_width_mm", "end_height_mm",
        "taper_power", "span_mm", "root_chord_mm", "tip_chord_mm", "thickness_pct", "sweep_deg",
        "dihedral_deg", "wing_position_pct", "section_a_pct", "section_b_pct",
    ):
        assert f"`{real_name}`" in prompt, f"missing real param name {real_name!r}"

    # the WRONG made-up names from the live repro must never appear anywhere in the prompt — proves
    # we are not accidentally reinforcing the guessed names alongside the real ones
    for wrong_name in (
        "fuselage_length_mm", "wing_span_mm", "wing_x_position_mm", "wing_naca_series",
    ):
        assert wrong_name not in prompt, f"guessed/wrong param name {wrong_name!r} leaked into prompt"


def test_system_prompt_does_not_duplicate_params_for_already_instantiated_subsystem(base_ledger):
    # bracket ALREADY has a real instance ("root") in base_ledger — its catalog param names must NOT
    # be listed a second, bare time in the "Part types" menu; they are already covered, correctly
    # instance-id-qualified, by the "Tunable parameters" section (_param_schema/_all_geometry_paths).
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    # the catalog-listing format _subsystems_section uses for a NOT-yet-instantiated subsystem is
    # "- `<bare name>` (<unit>, recommended [...])" (see _subsystems_section); the real, correctly
    # instance-id-qualified form _param_schema uses is "- `instances.root.params.<name>` (...)".
    # bracket already has a real "root" instance here, so the BARE catalog form must be absent
    # (proving no duplication) while the qualified form must be present (proving it's still covered).
    assert "- `instances.root.params.skin_thickness_mm` (mm, recommended [1.0, 5.0])" in prompt
    assert "- `skin_thickness_mm` (mm, recommended" not in prompt


def test_system_prompt_paces_a_vague_whole_vehicle_request_on_an_empty_file():
    # Live user feedback this session: a vague "build me a flying wing UAV" made the copilot add the
    # wing AND an electronics bay AND two spars in the same turn — the user wants the airframe
    # (outer mold line) established first, systems/mounting parts only once that shape exists.
    empty_ledger = make_demo_ledger()
    prompt = build_system_prompt(None, empty_ledger)
    assert "Airframe-first pacing" in prompt
    assert "Airframe already established" not in prompt
    # the real airframe-defining type names must be named so the copilot knows which ones count
    for name in ("naca_wing", "bwb_fuselage", "tube_fuselage", "ogive_fuselage", "winged_fuselage"):
        assert name in prompt


def test_system_prompt_stays_paced_with_only_a_non_airframe_part_present(base_ledger):
    # base_ledger's root instance is a plain "bracket" — not airframe-defining. The pacing rule must
    # still apply (a bracket existing doesn't mean the vehicle's shape is established).
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "Airframe-first pacing" in prompt
    assert "Airframe already established" not in prompt


def test_system_prompt_lifts_pacing_once_an_airframe_part_exists():
    led = make_demo_ledger()
    led = add_instance(led, "naca_wing", "main_wing")
    prompt = build_system_prompt(get_subsystem("naca_wing"), led)
    assert "Airframe already established" in prompt
    assert "Airframe-first pacing" not in prompt


def test_system_prompt_includes_every_instantiated_types_fragment_not_just_one():
    """foundations-audit follow-up (2026-07-21, live-verified): only `subsystem_ctx`'s own
    `prompt_fragment` (whichever ONE instance happened to be "active") was ever included — a genuine
    multi-domain assembly (a longeron + a bracket + a naca_wing in the same file, exactly the
    multi-subsystem case this engine exists for) got the design-intent/sizing-guidance fragment for
    only ONE of its three types; the other two got nothing beyond their bare name + param list. Also
    covers dedup: a second instance of an already-seen type must not repeat its fragment."""
    led = make_demo_ledger()
    led = add_instance(led, "longeron", "longeron1")
    led = add_instance(led, "bracket", "bracket1")
    led = add_instance(led, "naca_wing", "wing1")
    led = add_instance(led, "longeron", "longeron2")  # second instance of an already-seen type

    prompt = build_system_prompt(get_subsystem("longeron"), led)

    longeron_frag = get_subsystem("longeron").prompt_fragment
    bracket_frag = get_subsystem("bracket").prompt_fragment
    wing_frag = get_subsystem("naca_wing").prompt_fragment
    assert longeron_frag in prompt
    assert bracket_frag in prompt
    assert wing_frag in prompt
    assert prompt.count(longeron_frag) == 1  # deduped, not once per instance


def test_system_prompt_marks_a_locked_param_and_only_that_one(base_ledger):
    # mutation-sweep follow-up (2026-07-22): no test in this suite ever asserted on the literal
    # "LOCKED" marker text -- an undetected mutation inverted the condition, so every HARD_LOCK
    # param would render with NO warning (the copilot could propose a delta against something that
    # must never be touched) while every ordinary DYNAMIC param would falsely show as locked.
    locked = base_ledger.model_copy(deep=True)
    locked.instances["root"].params["skin_thickness_mm"] = (
        locked.instances["root"].params["skin_thickness_mm"].model_copy(
            update={"lock_state": LockState.HARD_LOCK}))
    prompt = build_system_prompt(get_subsystem("bracket"), locked)
    skin_line = next(l for l in prompt.splitlines() if "instances.root.params.skin_thickness_mm" in l)
    plate_line = next(l for l in prompt.splitlines() if "instances.root.params.plate_width_mm" in l)
    assert "[LOCKED" in skin_line
    assert "[LOCKED" not in plate_line


def test_system_prompt_lists_all_four_cross_cutting_params():
    # mutation-sweep follow-up: an undetected mutation silently dropped power_dissipation_w from the
    # cross-cutting param set every part gets shown -- the copilot would stop being able to
    # propose/adjust power-dissipation deltas at all, on a thermal/safety-adjacent input, since it
    # can only target a node it has actually seen listed.
    led = add_instance(make_demo_ledger(), "bracket", "root")
    prompt = build_system_prompt(get_subsystem("bracket"), led)
    for node in (BUILD_ORIENTATION, SLIP_FIT, OPERATING_TEMP, POWER_DISSIPATION):
        assert f"`{node}`" in prompt, f"missing cross-cutting node {node!r}"


def test_system_prompt_marks_active_on_the_right_subsystem_only(base_ledger):
    # mutation-sweep follow-up: an undetected mutation flipped the "— ACTIVE" marker's condition, so
    # every subsystem EXCEPT the actually-active one got tagged, misleading the copilot about which
    # part type the conversation is currently scoped to.
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    bracket_line = next(l for l in prompt.splitlines() if l.startswith("- **bracket**"))
    other_line = next(l for l in prompt.splitlines() if l.startswith("- **enclosure**"))
    assert "— ACTIVE" in bracket_line
    assert "— ACTIVE" not in other_line


def test_system_prompt_lists_the_new_box_and_bracket_face_interfaces():
    # 2026-07-22 antenna-bracket root-cause fix: enclosure/lbracket now declare mount interfaces, so
    # the copilot has a real connection_ops target instead of hand-computing a mount position.
    led = add_instance(make_demo_ledger(), "enclosure", "box")
    led = add_instance(led, "lbracket", "brk")
    prompt = build_system_prompt(get_subsystem("enclosure"), led)
    box_line = next(l for l in prompt.splitlines() if "interfaces (mate points" in l and "`left`" in l)
    for name in ("left", "right", "front", "back", "bottom", "top"):
        assert f"`{name}`" in box_line
    bracket_line = next(l for l in prompt.splitlines() if "interfaces (mate points" in l and "`wall_mount`" in l)
    assert "`top`" in bracket_line


def test_system_prompt_no_longer_tells_the_copilot_to_hand_compute_when_no_interface_exists():
    # foundations-audit follow-up (2026-07-22): _CONNECTION_OPS_SECTION used to say "reach for
    # explicit x/y/z when the parts have no matching interface" -- directly contradicting
    # _ASSEMBLY_CONNECTIVITY_SECTION's "you do NOT have enough information to hand-compute, use
    # auto-layout + disclose" for the identical trigger. The antenna-bracket placement bug is the
    # live symptom of a model reading the first (wrong) instruction.
    prompt = build_system_prompt(get_subsystem("bracket"), make_demo_ledger())
    assert "Only reach for explicit x/y/z when the parts genuinely have no matching interface" not in prompt
    assert "do NOT reach for a hand-computed x/y/z as a substitute" in prompt


def test_system_prompt_teaches_the_box_face_mount_recipe():
    prompt = build_system_prompt(get_subsystem("bracket"), make_demo_ledger())
    assert "wall_mount" in prompt and "flush against a box-shaped part's side" in prompt


def test_system_prompt_teaches_connection_kind_and_when_to_use_containment():
    # 2026-07-22: Connection.kind (mate/bolted/slip_fit/containment) was 100% advisory and the model
    # was never told it exists -- it always left connections at the default "mate", so the new
    # `interference` self-check's containment-aware exemption could never actually engage. Teaching
    # the model this vocabulary is what lets it express "this is intentionally nested" up front.
    prompt = build_system_prompt(get_subsystem("bracket"), make_demo_ledger())
    assert "\"containment\"" in prompt and "sit INSIDE or around another" in prompt
    assert "\"bolted\"" in prompt and "\"slip_fit\"" in prompt


def test_build_system_prompt_from_json_falls_back_cleanly_on_invalid_input():
    # mutation-sweep follow-up: build_system_prompt_from_json is NOT test-only scaffolding -- it's
    # called on the LIVE /chat path (openrouter_provider.py's stream_chat) to build the real system
    # prompt for every production conversation turn, and had ZERO direct test coverage anywhere in
    # this repo before this test. Its own docstring promises a graceful fallback to the bare
    # part-type menu for "incomplete/unparseable" ledger JSON -- never a crash, never a fabricated
    # ledger state ("never fake a green light"). Covers both failure shapes: not-JSON-at-all, and
    # valid JSON that fails MasterParametricLedger's own schema validation.
    for bad_json in ("not json at all {{{", '{"totally": "wrong shape"}'):
        prompt = build_system_prompt_from_json(bad_json)
        assert "Part types" in prompt  # the bare-menu fallback, not an exception


def test_eval_harness_computes_metrics(stub_provider):
    cases = [
        EvalCase("make the skin 3 mm", [(SKIN, 3.0)]),     # stub correct
        EvalCase("make it stronger", CLARIFY),             # stub clarifies (correct)
        EvalCase("make the skin 3 mm", [(SKIN, 99.0)]),    # stub returns 3.0 -> WRONG
    ]
    report = grade(stub_provider, cases)
    assert report.total == 3 and report.passed == 2       # one mismatch detected
    assert report.clarified == 1 and report.clarification_precision == 1.0
