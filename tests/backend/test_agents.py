"""Runtime agent layer: propose->review->commit session + eval harness (test-only stub provider)."""

from __future__ import annotations

from packages.agents.eval import CLARIFY, EvalCase, grade
from packages.agents.prompt_builder import build_system_prompt
from packages.agents.runtime import CoModelingSession
from packages.ledger.events import EventLog
from packages.ledger.nodes import SKIN
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


def test_eval_harness_computes_metrics(stub_provider):
    cases = [
        EvalCase("make the skin 3 mm", [(SKIN, 3.0)]),     # stub correct
        EvalCase("make it stronger", CLARIFY),             # stub clarifies (correct)
        EvalCase("make the skin 3 mm", [(SKIN, 99.0)]),    # stub returns 3.0 -> WRONG
    ]
    report = grade(stub_provider, cases)
    assert report.total == 3 and report.passed == 2       # one mismatch detected
    assert report.clarified == 1 and report.clarification_precision == 1.0
