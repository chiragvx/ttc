"""Runtime agent layer: propose->review->commit session + eval harness (test-only stub provider)."""

from __future__ import annotations

import dataclasses
import os

import pytest

from packages.agents.eval import GOLDEN_GRAPH, grade_live, grade_offline, run_case_offline
from packages.agents.prompt_builder import build_system_prompt, build_system_prompt_from_json
from packages.agents.runtime import CoModelingSession
from packages.ledger.deltas import DeltaProposal
from packages.ledger.events import EventLog
from packages.ledger.nodes import BUILD_ORIENTATION, OPERATING_TEMP, POWER_DISSIPATION, SKIN, SLIP_FIT
from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import Connection, InterfaceRef, ReviewState
from packages.subsystems import SUBSYSTEM_MODELS, SUBSYSTEM_REGISTRY, ParamSpec, add_instance, get_subsystem, get_subsystem_model
from packages.subsystems.base import EnvelopeSocketSpec
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


def test_system_prompt_teaches_purpose_aware_decomposition(base_ledger):
    # 2026-07-26 live repro: "a stand up on legs to hold my soldering iron" got mapped to a bare
    # `table` (a clean shape-match) with zero iron-holding feature -- the model treated a single-type
    # shape-match as automatically "done" even though the request stated a functional purpose the
    # matched type doesn't address. The prompt must teach that a stated purpose isn't optional context.
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "FUNCTIONAL PURPOSE" in prompt
    assert "soldering iron" in prompt.lower()
    assert "table" in prompt.lower()
    assert "not automatically" in prompt.lower() or "not.. automatically" in prompt.lower() \
        or 'not automatically "done"' in prompt.lower()


def test_system_prompt_teaches_cut_depth_sanity_on_hollow_parts(base_ledger):
    # 2026-07-26 live repro: proposing a 15mm pocket + three 20mm holes into a 35mm-tall,
    # 3mm-wall `enclosure` CONFLICTed all four times ("severed the part into 2 disconnected
    # islands") -- the prompt never taught checking a cut's depth against the target's own real
    # wall thickness before proposing it. Must now teach that check explicitly.
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "wall_thickness_mm" in prompt
    assert "disconnected" in prompt.lower() or "sever" in prompt.lower()
    assert "hollow" in prompt.lower()


def test_system_prompt_explains_the_connection_anchor_convention(base_ledger):
    # 2026-07-26 (inspired by an external CAD-skill reference's explicit "fixed-first, moving-second"
    # joint convention): resolve_placements' own anchor-selection rule (prefer an already-positioned
    # instance, else fall back to alphabetically-first instance id) was real and correct but never
    # explained to the model -- it had no way to know which side of a connection would end up fixed.
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "FIXED" in prompt and "MOVES" in prompt
    assert "alphabetically" in prompt.lower()
    assert "explicit position" in prompt.lower()


def test_system_prompt_teaches_deltas_is_sibling_not_nested_on_add_instance(base_ledger):
    # 2026-07-26 live repro: an `add_instance` for a `flat_bar` carried `length_mm`/`width_mm`/
    # `thickness_mm` directly on the op object instead of as separate top-level `deltas` entries --
    # Pydantic's extra_forbidden correctly rejected the whole call. The prompt must teach the actual
    # shape: deltas is a sibling list on the reply, never extra keys on the add_instance op itself.
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "sibling" in prompt.lower()
    assert "add_instance" in prompt and "deltas" in prompt


def test_system_prompt_teaches_there_is_no_top_level_rationale_on_the_reply(base_ledger):
    # 2026-07-26 live repro: a reply put a summary `rationale` at the top level alongside
    # `instance_ops` -- DeltaProposal has no such field (only individual ops do) and the whole call
    # was rejected. The prompt must teach where a turn-level "why" actually belongs.
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "no turn-level" in prompt.lower() or "not a real field" in prompt.lower()
    assert "prose reply" in prompt.lower()


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


def test_system_prompt_catalog_ranges_are_unambiguous_for_negative_min_params():
    # 2026-07-26 adversarial-review catch: the compact per-subsystem catalog format renders a param's
    # range as `name[min,max]unit` -- a plain `min-max` (no brackets/comma) would be genuinely
    # ambiguous whenever min is negative (e.g. sweep_deg's real range is -30 to 45, and "-30-45"
    # cannot be unambiguously split back into two numbers). bwb_fuselage's sweep_deg/dihedral_deg are
    # real live params with a negative min -- assert the actual bracketed, comma-separated form
    # survives so a negative-min range is always unambiguously recoverable.
    empty_ledger = make_demo_ledger()
    prompt = build_system_prompt(None, empty_ledger)
    assert "`sweep_deg`[-30,45]deg" in prompt
    assert "`dihedral_deg`[-10,20]deg" in prompt


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
    # the catalog-menu bullet for bracket (already instantiated as "root") must carry no compact
    # `params:` suffix at all -- the format is "- **name**[ -- ACTIVE]: description[ -- params: ...][ --
    # interfaces: ...]", so isolate bracket's own bullet line and assert it has no "params:" segment.
    bracket_line = next(l for l in prompt.splitlines() if l.startswith("- **bracket**"))
    assert "params:" not in bracket_line


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


# --- housing (gearbox-housing-generation initiative) pacing (2026-08-06, Phase 4) --------------------
# Mirrors the airframe-pacing tests immediately above: same "read the ledger, assert the right fragment
# for the right state" shape, one layer out (a 4-state housing sequence instead of a 2-state
# established/not-established switch). No real catalog subsystem declares `envelope_socket` yet (Phase
# 2's own scope is additive, zero real adopters — see tests/subsystems/test_envelope.py's own module
# docstring), so `housing_model` below monkeypatches a throwaway registry entry the same way that file
# does. `spur_gear` (registered, 2026-08-05) is the one real catalog subsystem with a `kind="mesh"`
# interface, so it stands in for "a kinematic part" without needing a monkeypatch of its own.

_HOUSING_TYPE = "_test_housing_pacing"


@pytest.fixture
def housing_model(monkeypatch):
    """Registers a throwaway `_test_housing_pacing` Subsystem (a `flat_bar`-shaped copy with
    `envelope_socket` set, PLUS three outer_* params for `_envelope_dims_still_pending` to compare
    against their own catalog defaults) — mirrors tests/backend/test_envelope_ops_transport.py's own
    `housing_model` fixture exactly."""
    base_model = get_subsystem_model("flat_bar")
    housing = dataclasses.replace(
        base_model, name=_HOUSING_TYPE,
        params=[
            *base_model.params,
            ParamSpec("outer_width_mm", value=1.0, min=0.1, max=2000.0, unit="mm"),
            ParamSpec("outer_depth_mm", value=1.0, min=0.1, max=2000.0, unit="mm"),
            ParamSpec("outer_height_mm", value=1.0, min=0.1, max=2000.0, unit="mm"),
        ],
        envelope_socket=EnvelopeSocketSpec(dim_params={
            "hull_bbox_x_mm": "outer_width_mm",
            "hull_bbox_y_mm": "outer_depth_mm",
            "hull_bbox_z_mm": "outer_height_mm",
        }),
    )
    monkeypatch.setitem(SUBSYSTEM_MODELS, _HOUSING_TYPE, housing)
    housing_ctx = dataclasses.replace(get_subsystem("flat_bar"), name=_HOUSING_TYPE)
    monkeypatch.setitem(SUBSYSTEM_REGISTRY, _HOUSING_TYPE, housing_ctx)
    return housing


def _mesh_connected_gear_pair(led):
    led = add_instance(led, "spur_gear", "gear1")
    led = add_instance(led, "spur_gear", "gear2")
    conn = Connection(id="mesh1", a=InterfaceRef(instance_id="gear1", interface="mesh"),
                      b=InterfaceRef(instance_id="gear2", interface="mesh"))
    return led.model_copy(update={"connections": [*led.connections, conn]})


def test_system_prompt_has_no_housing_pacing_fragment_without_any_housing_or_kinematic_part(base_ledger):
    # the common case (an ordinary project with no housing-family instance AND no kinematic-mesh
    # instance at all — base_ledger's root is a plain bracket, i.e. a NON-empty ledger that has
    # already shown its hand as unrelated) must see ZERO new prompt text.
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "Housing sequence" not in prompt


def test_system_prompt_hedges_housing_pacing_on_the_very_first_turn_of_an_empty_ledger():
    # R3-confirmed gap (2026-08-06): the section used to `return ""` unconditionally whenever neither a
    # housing-family nor a kinematic-mesh instance existed yet -- including a genuinely EMPTY ledger,
    # silencing it on the exact turn the reviewer's own worked example targets: a user's FIRST message
    # ("build me a 2-stage gearbox with a housing") against a fresh/empty ledger. Unlike the
    # already-unrelated-project case above (a non-empty ledger that already shows a bracket), an EMPTY
    # ledger is genuinely ambiguous, so this must now emit a hedged fragment mirroring
    # `_airframe_pacing_section`'s own always-on, wording-hedged posture.
    empty_ledger = make_demo_ledger()
    assert not empty_ledger.instances
    prompt = build_system_prompt(None, empty_ledger)
    assert "Housing sequence" in prompt
    assert "IF the user's request involves a multi-part kinematic assembly" in prompt
    assert "Do NOT also propose a housing-shaped part in this same turn" in prompt


def test_system_prompt_paces_toward_mate_connecting_kinematic_parts_before_any_housing(base_ledger):
    # a lone, unconnected spur_gear -- "no eligible kinematic parts placed yet ... via real
    # Connection/mesh interfaces" -- must propose mate-connecting it, never a housing yet.
    led = add_instance(base_ledger, "spur_gear", "gear1")
    prompt = build_system_prompt(get_subsystem("bracket"), led)
    assert "mate-connect the kinematic parts FIRST" in prompt
    assert "the kinematic cluster is ready, wrap it next" not in prompt
    assert "envelope derivation is still pending" not in prompt
    assert "derived dimensions are in, the shell is next" not in prompt


def test_system_prompt_paces_against_wrap_group_when_no_housing_family_instance_exists(base_ledger):
    # two spur_gears mesh-connected via a real connection_ops-shaped Connection, but NO housing-family
    # instance exists anywhere in the ledger yet (housings == []) -- the real-catalog state TODAY,
    # since no subsystem file declares `envelope_socket` (see this file's own module comment above).
    # R2 (2026-08-06): this state used to be mis-paced identically to "a housing already exists, just
    # wrap it" (below) -- telling the model to "propose wrap_group" with nothing real for
    # `housing_instance` to name, which `apply_envelope_op` REJECTS outright. Must instead say plainly
    # not to propose wrap_group yet, and must NOT say "wrap it next" (that's state 2b's fragment, for
    # when a housing instance actually already exists).
    led = _mesh_connected_gear_pair(base_ledger)
    prompt = build_system_prompt(get_subsystem("bracket"), led)
    assert "no housing-family part exists yet, don't propose wrap_group" in prompt
    assert "Do NOT invent a housing_instance id" in prompt
    assert "the kinematic cluster is ready, wrap it next" not in prompt
    assert "mate-connect the kinematic parts FIRST" not in prompt
    assert "envelope derivation is still pending" not in prompt
    assert "derived dimensions are in, the shell is next" not in prompt


def test_system_prompt_paces_toward_wrap_group_once_an_unwrapped_housing_instance_exists(base_ledger, housing_model):
    # two spur_gears mesh-connected, PLUS a REAL housing-family instance already in the ledger whose
    # `wraps` is still empty -- the state the old (buggy) test above actually meant to cover. Must
    # propose wrap_group next, naming the real existing housing instance id -- never the "no
    # housing-family part exists yet" fragment, since one genuinely does.
    led = _mesh_connected_gear_pair(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    prompt = build_system_prompt(get_subsystem("bracket"), led)
    assert "the kinematic cluster is ready, wrap it next" in prompt
    assert "wrap_group" in prompt
    assert "housing_instance='housing1'" in prompt
    assert "no housing-family part exists yet" not in prompt
    assert "mate-connect the kinematic parts FIRST" not in prompt
    assert "envelope derivation is still pending" not in prompt
    assert "derived dimensions are in, the shell is next" not in prompt


def test_system_prompt_paces_to_wait_while_envelope_dims_are_still_pending(base_ledger, housing_model):
    # housing1 already wraps the clean cluster, but its own outer_*_mm params are still sitting at
    # their catalog defaults -- the async derivation (Phase 3) hasn't landed -- must say wait, not
    # propose shell/DFM features.
    led = _mesh_connected_gear_pair(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["gear1", "gear2"]
    prompt = build_system_prompt(get_subsystem("bracket"), led)
    assert "envelope derivation is still pending" in prompt
    assert "the kinematic cluster is ready, wrap it next" not in prompt
    assert "mate-connect the kinematic parts FIRST" not in prompt
    assert "derived dimensions are in, the shell is next" not in prompt


def test_system_prompt_still_paces_to_wait_when_only_some_envelope_dims_are_populated(base_ledger, housing_model):
    # R1-precedent-fidelity (2026-08-06): housing1 wraps the clean cluster and ONLY outer_width_mm has
    # moved off its catalog default (e.g. a stray manual edit/delta landing before the Phase 3 async
    # derivation job finishes) -- outer_depth_mm/outer_height_mm are still literally 1.0, never derived.
    # `_envelope_dims_still_pending` must require EVERY mapped dim to differ from its default before
    # reporting "derived" -- one populated dim out of three must still say wait, never "the shell is
    # next" (which would steer the model into proposing shell/DFM features against two ungrounded
    # catalog-default placeholders, the exact "guessed-box housing" failure this phase exists to catch).
    led = _mesh_connected_gear_pair(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["gear1", "gear2"]
    led.instances["housing1"].params["outer_width_mm"] = ParameterDef(value=50.0, unit="mm", bounds=(0.1, 2000.0))
    prompt = build_system_prompt(get_subsystem("bracket"), led)
    assert "envelope derivation is still pending" in prompt
    assert "derived dimensions are in, the shell is next" not in prompt
    assert "the kinematic cluster is ready, wrap it next" not in prompt
    assert "mate-connect the kinematic parts FIRST" not in prompt


def test_system_prompt_paces_toward_housing_shell_once_envelope_dims_are_populated(base_ledger, housing_model):
    # same wrapped housing, but its outer_*_mm params now differ from their catalog defaults --
    # standing in for "the Phase 3 derivation already landed" -- must propose shell/DFM features now.
    led = _mesh_connected_gear_pair(base_ledger)
    led = add_instance(led, _HOUSING_TYPE, "housing1")
    led.instances["housing1"].wraps = ["gear1", "gear2"]
    led.instances["housing1"].params["outer_width_mm"] = ParameterDef(value=50.0, unit="mm", bounds=(0.1, 2000.0))
    led.instances["housing1"].params["outer_depth_mm"] = ParameterDef(value=20.0, unit="mm", bounds=(0.1, 2000.0))
    led.instances["housing1"].params["outer_height_mm"] = ParameterDef(value=10.0, unit="mm", bounds=(0.1, 2000.0))
    prompt = build_system_prompt(get_subsystem("bracket"), led)
    assert "derived dimensions are in, the shell is next" in prompt
    assert "envelope derivation is still pending" not in prompt
    assert "the kinematic cluster is ready, wrap it next" not in prompt
    assert "mate-connect the kinematic parts FIRST" not in prompt


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
    box_line = next(l for l in prompt.splitlines() if "interfaces:" in l and "`left`" in l)
    for name in ("left", "right", "front", "back", "bottom", "top"):
        assert f"`{name}`" in box_line
    bracket_line = next(l for l in prompt.splitlines() if "interfaces:" in l and "`wall_mount`" in l)
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


def test_graph_eval_offline_hard_gate_all_pass():
    """CI hard gate for the NEW graph-grading harness (packages/agents/eval_graph.py): every
    deterministic offline fixture in GOLDEN_GRAPH must reproduce its expected resulting graph exactly
    through the REAL stream_chat -> apply pipeline. Every fixture is hand-authored to represent
    CORRECT model behavior (see eval_graph.py's own module docstring), so a failure here is a REAL
    regression in packages.ledger/packages.subsystems/packages.agents — never model non-determinism,
    and never something to loosen/skip to get green (a drifted result here is signal)."""
    report = grade_offline(GOLDEN_GRAPH)
    failures = "\n".join(f"  {r.case.name}: {r.failures}" for r in report.results if not r.passed)
    assert report.passed == report.total, (
        f"{report.passed}/{report.total} GOLDEN_GRAPH cases passed offline:\n{failures}")


def test_never_invents_a_subsystem_type_is_a_hard_gate():
    """Task item 1 — the ONE non-negotiable hard invariant this eval harness enforces as a CI gate
    (everything else in GOLDEN_GRAPH is a reported structural/quality check, not necessarily a gate on
    its own — this one always is). A model that tries to add subsystem_type='satellite_body'
    (packages/agents/prompt_builder.py's OWN named counter-example of what must never be invented) is
    REJECTED by the RULES layer (apply_instance_op's known_subsystem_types check), never silently
    created — the schema alone can't catch this, since InstanceOp.subsystem_type is a plain str."""
    assert "satellite_body" not in SUBSYSTEM_REGISTRY, "test premise broken: this type is now real"
    case = next(c for c in GOLDEN_GRAPH
                if c.name == "invented_subsystem_type_is_rejected_not_silently_created")
    ctx = run_case_offline(case)
    assert ctx.proposal is not None  # the shape is valid JSON — schema alone doesn't block this
    assert any(o.status.value == "REJECTED" for o in ctx.op_log.instance)
    assert all(inst.subsystem_type in SUBSYSTEM_REGISTRY for inst in ctx.final_ledger.instances.values())
    assert "satellite_body" not in {i.subsystem_type for i in ctx.final_ledger.instances.values()}


def test_no_top_level_rationale_field_exists_on_deltaproposal():
    """Task item 5 — schema-shape hard gate. DeltaProposal must never grow a top-level `rationale`
    field: only individual ops carry their own rationale (packages/ledger/deltas.py). Pinned at BOTH
    the schema level (this field-absence assertion — the thing that would need to change for the
    2026-07-26 live failure to become "recoverable" instead of "wholesale rejected") AND the full
    stream_chat pipeline level (a proposal poisoned by this key must yield NO proposal event and
    apply NOTHING, never a partial/silent apply of the otherwise-good instance_ops alongside it)."""
    assert "rationale" not in DeltaProposal.model_fields
    case = next(c for c in GOLDEN_GRAPH if c.name == "top_level_rationale_poisons_the_whole_call")
    ctx = run_case_offline(case)
    assert ctx.proposal is None
    assert any(kind == "error" for kind, _ in ctx.events)
    assert not ctx.final_ledger.instances  # the otherwise-good add_instance never silently landed


def test_smuggled_add_instance_dims_are_recovered_not_lost():
    """Task item 4 — schema-shape hard gate. A dimension smuggled directly onto add_instance
    (2026-07-27 live failure — deltas.py::DeltaProposal._repair_known_wire_quirks) must be recovered
    into the sibling `deltas` list and actually APPLIED — never silently dropped, never left crashing
    the whole call, and never left sitting as an illegal extra field on the op itself."""
    case = next(c for c in GOLDEN_GRAPH if c.name == "smuggled_dims_on_add_instance_are_recovered")
    ctx = run_case_offline(case)
    assert ctx.proposal is not None
    op = ctx.proposal.instance_ops[0]
    assert not hasattr(op, "length_mm")  # InstanceOp's own schema has no such field at all
    bar = ctx.final_ledger.instances["bar_1"]
    assert bar.params["length_mm"].value == 500.0
    assert bar.params["width_mm"].value == 20.0
    assert bar.params["thickness_mm"].value == 5.0


@pytest.mark.live
def test_graph_eval_live_accuracy_report():
    """OPTIONAL live-quality report (same key-gated posture as tests/live/test_openrouter_live.py):
    grades GOLDEN_GRAPH's prompts against a REAL model. Reports an accuracy NUMBER only — NEVER a
    hard gate, since model output is non-deterministic and a flaky red build here would just train
    people to ignore CI (this task's own design constraint)."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider

    provider = OpenRouterDeltaProvider()
    report = grade_live(provider, GOLDEN_GRAPH)
    print(f"\nlive graph-eval accuracy: {report.passed}/{report.total} ({report.accuracy:.0%})")
    for r in report.results:
        if not r.passed:
            print(f"  MISS {r.case.name}: {r.failures}")
    # intentionally no assertion on report.accuracy/report.passed — see docstring.
