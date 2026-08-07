"""Phase 3 of the AI-generated-custom-geometry initiative (2026-08-06) —
`packages/subsystems/generated_registration.py`: the GATE that composes Phases 0/1/2 into the decision
of whether a candidate becomes a real, permanent, restart-surviving catalog subsystem.

TEST-DIRECTORY CHOICE: lives under tests/subsystems/, NOT tests/backend/. `generated_registration.py`
itself lives at packages/subsystems/generated_registration.py (not under packages/truth_plane/), and its
central subject under test — the four-floor GATE deciding SUBSYSTEM_REGISTRY membership, the
provenance-banner module renderer, and (the acid test) restart-survival via the real
`packages.subsystems._discover_generated_subsystems()` — is subsystems-catalog territory: it directly
extends and reuses packages/subsystems/__init__.py's own registration/discovery mechanism, mirroring
Phase 0's own test (tests/subsystems/test_generated_discovery.py), including its exact `_clean_registry`
fixture pattern (registry/sys.modules leak cleanup) reused here near-verbatim. It calls INTO
packages/truth_plane (sandbox_subsystem.sandbox_build_and_validate, generated_subsystem_store) and
packages/ledger (events.EventLog) as dependencies — the same relationship Phase 0's own file already has
with packages/ledger/apply.py's assembly-template reconciliation — without those dependencies making the
FILE ITSELF truth_plane- or ledger-adjacent code. Phase 1's/Phase 2's own tests (tests/backend/
test_sandbox_subsystem.py, tests/backend/test_generated_subsystem_store.py) correctly live in
tests/backend/ because THEY live under packages/truth_plane/ themselves — this file does not.

Needs-kernel scope (same convention as tests/backend/test_sandbox_subsystem.py, matched from
tests/subsystems/test_spur_gear.py's own HAS_*/find_spec + skipif pattern): only the tests that make a
candidate actually build real geometry through the sandbox (the accepted box, the degenerate
self-subtraction, the combined-corpus sweep, the acid test) need build123d and carry
`@pytest.mark.needs_kernel` + a `skipif`. The BUILD_ERROR/disallowed-import/name-collision/invalid-
identifier/render-safety tests never touch build123d (either the candidate code itself never imports it,
or the floor being tested rejects before the sandbox is ever reached) and run unmarked, on any machine.

Every test writes generated modules to `tmp_path` (the `generated_dir` override), never the real
packages/subsystems/generated/ — satisfies this phase's own cleanup requirement by construction, no
teardown needed for on-disk state.
"""

from __future__ import annotations

import ast
import base64
import importlib.util
import sys
import threading

import pytest

import packages.subsystems as subsystems_pkg
from packages.ledger.events import EventLog
from packages.subsystems import generated_registration as generated_registration_module
from packages.subsystems import get_subsystem_model
from packages.subsystems.generated_registration import (
    FLOOR_DISALLOWED_CODE,
    FLOOR_INVALID_IDENTIFIER,
    FLOOR_NAME_COLLISION,
    FLOOR_POST_SANDBOX_REGISTRATION_ERROR,
    FLOOR_SANDBOX_BUILD,
    SANDBOX_NOT_RUN,
    GeneratedSubsystemCandidate,
    register_generated_subsystem,
    render_subsystem_module,
)
from packages.truth_plane.generated_subsystem_store import InMemoryGenerationAttemptStore

HAS_B123D = importlib.util.find_spec("build123d") is not None

_MODEL_ID = "anthropic/claude-test-model"
_PROJECT_ID = "proj_phase3_test"

_GOOD_BOX_BUILD_CODE = (
    "def build(p):\n"
    "    import build123d as bd\n"
    "    return bd.Box(p.width_mm, p.depth_mm, p.height_mm)\n"
)
_GOOD_BOX_PARAMS = [
    {"name": "width_mm", "default": 10.0, "min": 1.0, "max": 100.0, "unit": "mm"},
    {"name": "depth_mm", "default": 8.0, "min": 1.0, "max": 100.0, "unit": "mm"},
    {"name": "height_mm", "default": 6.0, "min": 1.0, "max": 100.0, "unit": "mm"},
]

_RAISER_BUILD_CODE = (
    "def build(p):\n"
    "    raise ValueError('phase3 test boom')\n"
)

_DEGENERATE_BUILD_CODE = (
    "def build(p):\n"
    "    import build123d as bd\n"
    "    a = bd.Box(10, 10, 10)\n"
    "    return a - a\n"
)

_DISALLOWED_IMPORT_BUILD_CODE = (
    "import os\n"
    "def build(p):\n"
    "    return None\n"
)

_OPEN_CALL_BUILD_CODE = (
    "def build(p):\n"
    "    open('/etc/passwd')\n"
    "    return None\n"
)


def _candidate(name: str, build_code: str, params: list[dict] | None = None, **overrides) -> GeneratedSubsystemCandidate:
    fields = dict(
        subsystem_name=name,
        description=f"Phase 3 test fixture -- {name}, never a real catalog part",
        build_code=build_code,
        params=params or [],
        model=_MODEL_ID,
        project_id=_PROJECT_ID,
        user_request_excerpt="build me a test widget",
    )
    fields.update(overrides)
    return GeneratedSubsystemCandidate(**fields)


@pytest.fixture
def _clean_registry():
    """Mirrors tests/subsystems/test_generated_discovery.py::_clean_registry exactly -- discovery/
    registration mutate the module-level SUBSYSTEM_REGISTRY/SUBSYSTEM_MODELS dicts (the same global
    state production uses), so track what existed before and remove only what a test actually added."""
    before = set(subsystems_pkg.SUBSYSTEM_REGISTRY)
    before_modules = set(sys.modules)
    yield
    for name in set(subsystems_pkg.SUBSYSTEM_REGISTRY) - before:
        subsystems_pkg.SUBSYSTEM_REGISTRY.pop(name, None)
        subsystems_pkg.SUBSYSTEM_MODELS.pop(name, None)
    for mod_name in set(sys.modules) - before_modules:
        if mod_name.startswith("packages.subsystems.generated."):
            sys.modules.pop(mod_name, None)


def _bbox_extents(bbox_mm) -> list[float]:
    (min_corner, max_corner) = bbox_mm
    return sorted(round(mx - mn, 6) for mn, mx in zip(min_corner, max_corner))


# --- (a) good candidate -> ACCEPTED ------------------------------------------------------------------


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_good_box_candidate_is_accepted_and_resolves_via_get_subsystem_model(tmp_path, _clean_registry):
    store = InMemoryGenerationAttemptStore()
    log = EventLog()
    candidate = _candidate("gen_test_good_box_2026", _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS)

    result = register_generated_subsystem(candidate, store=store, event_log=log, generated_dir=tmp_path)

    assert result.accepted is True
    assert result.outcome == "registered"
    assert result.rejected_floor is None
    assert result.rejection_reason is None
    assert result.sandbox_status == "OK"
    assert result.volume_mm3 == pytest.approx(10.0 * 8.0 * 6.0)
    assert _bbox_extents(result.bbox_mm) == [6.0, 8.0, 10.0]

    model = get_subsystem_model("gen_test_good_box_2026")
    assert model.name == "gen_test_good_box_2026"
    assert [p.name for p in model.params] == ["width_mm", "depth_mm", "height_mm"]
    assert model.fea_eligible is False  # hardcoded by the template, never candidate-supplied

    row = store.get(result.attempt_id)
    assert row is not None
    assert row.outcome == "registered"
    assert row.rejection_reason is None
    assert row.subsystem_name == "gen_test_good_box_2026"
    assert row.model == _MODEL_ID
    assert row.project_id == _PROJECT_ID
    assert row.sandbox_status == "OK"
    assert row.volume_mm3 == pytest.approx(480.0)
    assert sorted(round(v, 6) for v in row.bbox_mm) == [6.0, 8.0, 10.0]
    # full ParamSpec-shaped dicts (name/default/min/max/unit), matching what the candidate declared
    stored = [{"name": d["name"], "default": d["default"], "min": d["min"], "max": d["max"],
               "unit": d["unit"]} for d in row.params]
    assert stored == _GOOD_BOX_PARAMS

    events = log.events()
    assert len(events) == 1
    assert events[0].payload == {
        "attempt_id": result.attempt_id, "sha256": row.sha256, "subsystem_name": "gen_test_good_box_2026",
        "model": _MODEL_ID, "outcome": "registered",
    }
    assert events[0].actor == f"ai:{_MODEL_ID}"
    assert log.verify_chain() is True

    written = tmp_path / "gen_test_good_box_2026.py"
    assert written.exists()
    assert "fea_eligible=False" in written.read_text(encoding="utf-8")


# --- (b) a build_code that raises inside build() -> rejected at floor 4, BUILD_ERROR ------------------


def test_build_error_candidate_is_rejected_at_sandbox_floor_with_build_error_reason(tmp_path, _clean_registry):
    store = InMemoryGenerationAttemptStore()
    candidate = _candidate("gen_test_raiser_2026", _RAISER_BUILD_CODE)

    result = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)

    assert result.accepted is False
    assert result.outcome == "rejected"
    assert result.rejected_floor == FLOOR_SANDBOX_BUILD
    assert result.sandbox_status == "BUILD_ERROR"
    assert "phase3 test boom" in result.rejection_reason

    with pytest.raises(KeyError):
        get_subsystem_model("gen_test_raiser_2026")

    row = store.get(result.attempt_id)
    assert row.outcome == "rejected"
    assert row.sandbox_status == "BUILD_ERROR"
    assert "phase3 test boom" in row.rejection_reason

    assert not (tmp_path / "gen_test_raiser_2026.py").exists()


# --- (c) degenerate geometry (self-subtraction) -> rejected at floor 4, DEGENERATE --------------------


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_degenerate_candidate_is_rejected_at_sandbox_floor_with_degenerate_reason(tmp_path, _clean_registry):
    store = InMemoryGenerationAttemptStore()
    candidate = _candidate("gen_test_degenerate_2026", _DEGENERATE_BUILD_CODE)

    result = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)

    assert result.accepted is False
    assert result.rejected_floor == FLOOR_SANDBOX_BUILD
    assert result.sandbox_status == "DEGENERATE"
    assert result.volume_mm3 == pytest.approx(0.0)

    with pytest.raises(KeyError):
        get_subsystem_model("gen_test_degenerate_2026")

    row = store.get(result.attempt_id)
    assert row.sandbox_status == "DEGENERATE"
    assert row.volume_mm3 == pytest.approx(0.0)
    assert not (tmp_path / "gen_test_degenerate_2026.py").exists()


# --- (d) disallowed import -> rejected at floor 3, sandbox never reached -------------------------------


def test_disallowed_import_is_rejected_at_denylist_floor_without_reaching_sandbox(
    tmp_path, _clean_registry, monkeypatch,
):
    calls: list[tuple] = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("sandbox_build_and_validate must never be called for a floor-3 rejection")

    monkeypatch.setattr(generated_registration_module, "sandbox_build_and_validate", _spy)

    store = InMemoryGenerationAttemptStore()
    candidate = _candidate("gen_test_disallowed_import_2026", _DISALLOWED_IMPORT_BUILD_CODE)

    result = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)

    assert calls == []  # the spy proves sandbox_build_and_validate was never invoked
    assert result.accepted is False
    assert result.rejected_floor == FLOOR_DISALLOWED_CODE
    assert result.sandbox_status is None  # never ran
    assert "os" in result.rejection_reason

    row = store.get(result.attempt_id)
    assert row.sandbox_status == SANDBOX_NOT_RUN
    assert not (tmp_path / "gen_test_disallowed_import_2026.py").exists()


def test_open_call_is_also_rejected_at_denylist_floor(tmp_path, _clean_registry, monkeypatch):
    monkeypatch.setattr(
        generated_registration_module, "sandbox_build_and_validate",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not reach sandbox")),
    )
    store = InMemoryGenerationAttemptStore()
    candidate = _candidate("gen_test_open_call_2026", _OPEN_CALL_BUILD_CODE)

    result = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)

    assert result.rejected_floor == FLOOR_DISALLOWED_CODE
    assert "open" in result.rejection_reason


# --- (e) name collision with a real catalog subsystem -> rejected at floor 1 --------------------------


def test_name_collision_with_existing_catalog_subsystem_is_rejected_at_floor_1(
    tmp_path, _clean_registry, monkeypatch,
):
    monkeypatch.setattr(
        generated_registration_module, "sandbox_build_and_validate",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not reach sandbox")),
    )
    store = InMemoryGenerationAttemptStore()
    real_washer_model = get_subsystem_model("washer")
    candidate = _candidate("washer", _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS)

    result = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)

    assert result.accepted is False
    assert result.rejected_floor == FLOOR_NAME_COLLISION
    assert "washer" in result.rejection_reason

    # the real washer is completely untouched
    assert get_subsystem_model("washer") is real_washer_model
    assert [p.name for p in get_subsystem_model("washer").params] == [
        "outer_dia_mm", "inner_dia_mm", "thickness_mm",
    ]
    assert not (tmp_path / "washer.py").exists()


# --- (f) R3 regression: two concurrent registrations of the SAME new name -----------------------------


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_concurrent_registration_of_the_same_new_name_has_exactly_one_winner(
    tmp_path, _clean_registry, monkeypatch,
):
    """R3 CONFIRMED FINDING regression: the floor-1 name-collision check and the later unconditional
    `path.write_text()` used to be unprotected by any lock, so two concurrent
    `register_generated_subsystem()` calls proposing the SAME brand-new `subsystem_name` could both pass
    the early floor-1 check (before either had written anything), both pass floors 2-4 independently, and
    both call `path.write_text()` for the identical target path -- whichever write landed last silently
    won on disk even though only the FIRST candidate to reach `_import_generated_module` ends up in
    SUBSYSTEM_REGISTRY for the rest of this process's life. Deterministically reproduces the race (rather
    than hoping OS thread scheduling happens to interleave two calls) by making the (real, out-of-process)
    sandboxed build -- floor 4, reached only AFTER both threads have already passed the early,
    unlocked floor-1 check -- rendezvous on a `threading.Barrier` before either proceeds, so both threads
    are guaranteed to be mid-flight, past floor 1, at the same time."""
    name = "gen_test_concurrent_race_2026"
    barrier = threading.Barrier(2)
    real_sandbox = generated_registration_module.sandbox_build_and_validate

    def _synced_sandbox(build_code, params):
        barrier.wait(timeout=10)
        return real_sandbox(build_code, params)

    monkeypatch.setattr(generated_registration_module, "sandbox_build_and_validate", _synced_sandbox)

    store = InMemoryGenerationAttemptStore()
    results: list = [None, None]

    def _run(i: int) -> None:
        candidate = _candidate(name, _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS)
        results[i] = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)

    threads = [threading.Thread(target=_run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive()  # fail loudly instead of hanging if the fix ever deadlocks

    outcomes = sorted(r.outcome for r in results)
    assert outcomes == ["registered", "rejected"]  # exactly one winner, never both, never neither

    winner = results[0] if results[0].outcome == "registered" else results[1]
    loser = results[1] if winner is results[0] else results[0]
    assert loser.rejected_floor == FLOOR_NAME_COLLISION
    assert winner.attempt_id != loser.attempt_id

    # exactly one file on disk, and its content is the WINNER's own attempt -- never the loser's write
    # silently landing last and overwriting it (the defect this regresses).
    written = tmp_path / f"{name}.py"
    assert written.exists()
    content = written.read_text(encoding="utf-8")
    assert winner.attempt_id in content
    assert loser.attempt_id not in content

    # in-memory registration matches the on-disk file -- no divergence between the two.
    model = get_subsystem_model(name)
    assert model.name == name

    # the corpus recorded BOTH attempts (unconditional capture, regardless of the race's outcome).
    row_winner = store.get(winner.attempt_id)
    row_loser = store.get(loser.attempt_id)
    assert row_winner is not None and row_winner.outcome == "registered"
    assert row_loser is not None and row_loser.outcome == "rejected"


# --- bonus floor coverage: invalid identifier ----------------------------------------------------------


@pytest.mark.parametrize("bad_name", ["not a valid name", "2cool4school", "class", "../evil", "has.dot"])
def test_invalid_identifier_is_rejected_at_floor_2(tmp_path, _clean_registry, bad_name):
    store = InMemoryGenerationAttemptStore()
    candidate = _candidate(bad_name, _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS)

    result = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)

    assert result.accepted is False
    assert result.rejected_floor == FLOOR_INVALID_IDENTIFIER


# --- all 5 canonical cases captured in the corpus regardless of outcome -------------------------------


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_all_five_canonical_cases_are_captured_in_the_corpus_with_distinct_reasons(tmp_path, _clean_registry):
    store = InMemoryGenerationAttemptStore()
    log = EventLog()

    good = register_generated_subsystem(
        _candidate("gen_test_corpus_good_2026", _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS),
        store=store, event_log=log, generated_dir=tmp_path,
    )
    build_error = register_generated_subsystem(
        _candidate("gen_test_corpus_raiser_2026", _RAISER_BUILD_CODE),
        store=store, event_log=log, generated_dir=tmp_path,
    )
    degenerate = register_generated_subsystem(
        _candidate("gen_test_corpus_degenerate_2026", _DEGENERATE_BUILD_CODE),
        store=store, event_log=log, generated_dir=tmp_path,
    )
    disallowed = register_generated_subsystem(
        _candidate("gen_test_corpus_disallowed_2026", _DISALLOWED_IMPORT_BUILD_CODE),
        store=store, event_log=log, generated_dir=tmp_path,
    )
    collision = register_generated_subsystem(
        _candidate("washer", _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS),
        store=store, event_log=log, generated_dir=tmp_path,
    )

    outcomes = [good.outcome, build_error.outcome, degenerate.outcome, disallowed.outcome, collision.outcome]
    assert outcomes == ["registered", "rejected", "rejected", "rejected", "rejected"]
    floors = [build_error.rejected_floor, degenerate.rejected_floor, disallowed.rejected_floor,
              collision.rejected_floor]
    assert floors == [FLOOR_SANDBOX_BUILD, FLOOR_SANDBOX_BUILD, FLOOR_DISALLOWED_CODE, FLOOR_NAME_COLLISION]

    rows = store.list(project_id=_PROJECT_ID)
    assert len(rows) == 5

    rejection_reasons = [r.rejection_reason for r in rows if r.outcome == "rejected"]
    assert len(rejection_reasons) == 4
    assert all(rejection_reasons)  # every one is non-empty
    assert len(set(rejection_reasons)) == 4  # all four are distinguishable from each other

    registered_rows = [r for r in rows if r.outcome == "registered"]
    assert len(registered_rows) == 1
    assert registered_rows[0].rejection_reason is None

    assert len(log.events()) == 5
    assert log.verify_chain() is True


# --- render_subsystem_module: candidate build_code embedded safely -------------------------------------


def test_render_module_embeds_hostile_build_code_safely_and_produces_valid_python():
    hostile_build_code = (
        "def build(p):\n"
        '    s = """triple\nquoted\nstring"""\n'
        "    t = '''another\ntriple'''\n"
        "    # a comment with an embedded token: __BUILD_CODE_B64__\n"
        "    return None\n"
    )
    candidate = _candidate("gen_test_hostile_2026", hostile_build_code, _GOOD_BOX_PARAMS)

    module_src = render_subsystem_module(candidate, attempt_id="att_test_hostile")

    tree = ast.parse(module_src)  # must still be valid Python -- proves nothing broke out
    assert isinstance(tree, ast.Module)

    marker = '_BUILD_CODE_B64 = "'
    start = module_src.index(marker) + len(marker)
    end = module_src.index('"', start)
    decoded = base64.b64decode(module_src[start:end]).decode("utf-8")
    assert decoded == hostile_build_code  # round-trips byte-for-byte, not mangled/truncated

    # the provenance banner is present and never candidate-controlled
    assert "att_test_hostile" in module_src
    assert "fea_eligible=False" in module_src


def test_render_module_preserves_a_param_unit_that_is_literally_a_later_placeholder_token():
    """Regression for the CONFIRMED high-severity R1 finding: `render_subsystem_module` used to chain
    `.replace()` calls on the progressively-ACCUMULATED template string, so a later substitution (e.g.
    `__BUILD_CODE_B64__`) would re-scan -- and could overwrite -- text an earlier substitution (e.g. a
    param's `unit=__DISCIPLINES_REPR_repr...` no, simpler: a param's repr()-quoted `unit`) had already
    spliced in, whenever that earlier string happened to literally contain a later placeholder token's
    text. Live-reproduced with exactly the finding's own repro: a param whose `unit` IS the literal
    string `"__BUILD_CODE_B64__"`. Before the fix this silently spliced the base64-encoded build_code
    blob into the rendered `ParamSpec(..., unit=...)` literal -- the module still compiled/imported fine
    (nothing rejected it), so `unit` came back corrupted with no error anywhere. After the fix, a single
    `re.sub` pass over the fixed template can never do this, regardless of what any candidate string
    contains."""
    candidate = _candidate(
        "gen_manual_silent_corrupt",
        "def build(p):\n    import build123d as bd\n    return bd.Box(p.w, 1, 1)\n",
        params=[{"name": "w", "default": 5.0, "min": 1.0, "max": 10.0, "unit": "__BUILD_CODE_B64__"}],
    )

    module_src = render_subsystem_module(candidate, attempt_id="att_test_silent_corrupt")

    tree = ast.parse(module_src)  # must still be valid Python
    assert isinstance(tree, ast.Module)

    # find the rendered ParamSpec(...) call and confirm unit is untouched, not the base64 build_code blob
    param_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "ParamSpec"
    ]
    assert len(param_calls) == 1
    unit_kwargs = [kw for kw in param_calls[0].keywords if kw.arg == "unit"]
    assert len(unit_kwargs) == 1
    assert isinstance(unit_kwargs[0].value, ast.Constant)
    assert unit_kwargs[0].value.value == "__BUILD_CODE_B64__"  # exactly what the candidate supplied

    # the base64 build_code blob is present exactly once (the real _BUILD_CODE_B64 assignment) -- never
    # ALSO spliced into the unit literal
    assert module_src.count("_BUILD_CODE_B64 = ") == 1


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_registered_subsystem_preserves_param_unit_containing_a_later_placeholder_token(tmp_path, _clean_registry):
    """Same regression as above, exercised end to end through the real gate (floors + render + write +
    in-process import) exactly as R1's finding reproduced it: the candidate is ACCEPTED (all four floors
    are mechanical-correctness floors, blind to this kind of content collision), and
    `get_subsystem_model(...).params[0].unit` must come back as the candidate's real `'__BUILD_CODE_B64__'`
    string, never the corrupted base64 build_code blob."""
    store = InMemoryGenerationAttemptStore()
    candidate = _candidate(
        "gen_test_silent_corrupt_2026",
        "def build(p):\n    import build123d as bd\n    return bd.Box(p.w, 1, 1)\n",
        params=[{"name": "w", "default": 5.0, "min": 1.0, "max": 10.0, "unit": "__BUILD_CODE_B64__"}],
    )

    result = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)

    assert result.accepted is True
    assert result.outcome == "registered"

    model = get_subsystem_model("gen_test_silent_corrupt_2026")
    assert model.params[0].unit == "__BUILD_CODE_B64__"


def test_render_module_never_lets_candidate_strings_override_fea_eligible():
    """A hostile description/subsystem_name trying to inject `fea_eligible=True` via string content
    must land only as an inert, repr()-quoted string literal argument -- never as executable code. The
    hostile substring "fea_eligible=True" DOES still appear somewhere in module_src (as inert text
    inside the quoted description literal) -- that alone proves nothing; what matters is what the AST
    says the real register_subsystem(Subsystem(...)) call's fea_eligible KEYWORD ARGUMENT actually is."""
    candidate = _candidate(
        "gen_test_injection_2026", _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS,
        description='")); fea_eligible=True  # trying to break out\nregister_subsystem(Subsystem(name="pwned',
    )
    module_src = render_subsystem_module(candidate, attempt_id="att_test_injection")

    tree = ast.parse(module_src)
    assert isinstance(tree, ast.Module)
    # exactly one register_subsystem(...) call in the whole rendered module -- the hostile description
    # never became a second, independent statement
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "register_subsystem"]
    assert len(calls) == 1

    subsystem_call = calls[0].args[0]  # Subsystem(...) is register_subsystem's sole positional arg
    assert isinstance(subsystem_call, ast.Call)
    fea_kwargs = [kw for kw in subsystem_call.keywords if kw.arg == "fea_eligible"]
    assert len(fea_kwargs) == 1  # exactly one fea_eligible= keyword argument, not two competing ones
    assert isinstance(fea_kwargs[0].value, ast.Constant)
    assert fea_kwargs[0].value.value is False  # HARDCODED False -- never flipped by candidate text


# --- THE ACID TEST: restart-survival end to end ---------------------------------------------------------


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_registered_subsystem_survives_fresh_discovery_after_removal_from_registry(tmp_path, _clean_registry):
    """THE ACID TEST (per the plan: 'the single most important correctness proof in this plan') -- after
    a real acceptance, prove RESTART-SURVIVAL end to end, not just 'it registered once in the same
    process'. Removes the type from the in-memory registry dicts first (simulating a fresh process that
    has never registered it), then calls Phase 0's REAL `_discover_generated_subsystems()` against the
    real file this call wrote to disk, and confirms the type resolves again -- proving discovery, not
    the original in-process registration, is what makes it resolve.

    Chosen over spawning a fresh `python -c` subprocess (the plan's other option): exercising the real
    discovery function directly is less flaky on this Windows dev box (no dependency on getting
    PYTHONPATH/interpreter selection right for a spawned child) while still genuinely re-reading from
    disk via the identical importlib mechanics a real restart uses -- not merely re-asserting that the
    in-memory dict was mutated during the original registration call."""
    store = InMemoryGenerationAttemptStore()
    name = "gen_test_acid_2026"
    result = register_generated_subsystem(
        _candidate(name, _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS), store=store, generated_dir=tmp_path,
    )
    assert result.accepted is True
    original_model = get_subsystem_model(name)
    written_file = tmp_path / f"{name}.py"
    assert written_file.exists()

    # Simulate a fresh process: remove every trace of the in-memory registration this call just made.
    subsystems_pkg.SUBSYSTEM_REGISTRY.pop(name, None)
    subsystems_pkg.SUBSYSTEM_MODELS.pop(name, None)
    for mod_name in [m for m in sys.modules if m.startswith("packages.subsystems.generated.")]:
        sys.modules.pop(mod_name, None)
    with pytest.raises(KeyError):
        get_subsystem_model(name)

    # The real Phase 0 discovery function, run fresh against the real file already on disk.
    subsystems_pkg._discover_generated_subsystems(directory=tmp_path)

    rediscovered_model = get_subsystem_model(name)
    assert rediscovered_model.name == name
    assert [p.name for p in rediscovered_model.params] == ["width_mm", "depth_mm", "height_mm"]
    assert rediscovered_model.fea_eligible is False
    # a genuinely NEW object produced by fresh exec -- not the original object surviving some other way
    assert rediscovered_model is not original_model


# --- post-sandbox registration error -> no orphaned .py file left on disk -----------------------------


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_post_sandbox_registration_error_leaves_no_orphaned_file_on_disk(
    tmp_path, _clean_registry, monkeypatch,
):
    """R1 CONFIRMED FINDING regression: a candidate that passes all four floors (sandbox genuinely
    succeeds) but then fails during render/write/import must come back 'rejected' at
    FLOOR_POST_SANDBOX_REGISTRATION_ERROR with NO trace of a .py file left on disk -- the same invariant
    every floor-1..4 rejection test in this suite asserts. Forces that failure by stubbing only
    `_import_generated_module` (the last step, after `path.write_text()` has already run) rather than
    reimplementing the whole gate -- everything up through a real, successful sandbox build (floors 1-4)
    still runs for real."""
    monkeypatch.setattr(
        generated_registration_module, "_import_generated_module",
        lambda path: (_ for _ in ()).throw(ImportError("simulated post-render import failure")),
    )
    store = InMemoryGenerationAttemptStore()
    log = EventLog()
    name = "gen_test_post_sandbox_orphan_2026"
    candidate = _candidate(name, _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS)

    result = register_generated_subsystem(candidate, store=store, event_log=log, generated_dir=tmp_path)

    assert result.accepted is False
    assert result.outcome == "rejected"
    assert result.rejected_floor == FLOOR_POST_SANDBOX_REGISTRATION_ERROR
    assert "simulated post-render import failure" in result.rejection_reason

    # the file write_text() performed before the simulated failure must not survive the rejection
    assert not (tmp_path / f"{name}.py").exists()

    # no stale sys.modules entry left behind by the partially-executed import either
    assert f"packages.subsystems.generated._{name}" not in sys.modules

    with pytest.raises(KeyError):
        get_subsystem_model(name)

    row = store.get(result.attempt_id)
    assert row is not None
    assert row.outcome == "rejected"
    assert "simulated post-render import failure" in row.rejection_reason
    assert log.verify_chain() is True


# --- misc: event_log is optional; store defaults to generation_attempt_store_from_env -----------------


def test_event_log_is_optional(tmp_path, _clean_registry):
    store = InMemoryGenerationAttemptStore()
    candidate = _candidate("gen_test_no_eventlog_2026", _RAISER_BUILD_CODE)

    result = register_generated_subsystem(candidate, store=store, generated_dir=tmp_path)  # no event_log

    assert result.outcome == "rejected"
    assert store.get(result.attempt_id) is not None


def test_store_defaults_to_an_honest_in_memory_fallback_when_not_supplied(tmp_path, _clean_registry, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    candidate = _candidate("gen_test_default_store_2026", _RAISER_BUILD_CODE)

    result = register_generated_subsystem(candidate, generated_dir=tmp_path)  # no store= supplied either

    assert result.outcome == "rejected"  # proves it ran end to end without crashing on the default wiring


# --- corpus-store write failure must never raise out of register_generated_subsystem ------------------
# Phase 5 write-path repair (2026-08-06, reviewer R2 CONFIRMED, medium): `_finish()`'s
# `resolved_store.put(attempt)` call used to sit completely unguarded. For the "registered" outcome
# specifically, `_finish` runs AFTER the candidate's module has already been rendered, written to disk,
# and imported into SUBSYSTEM_REGISTRY -- a real, permanent mutation nothing in this function rolls
# back -- so a `GenerationAttemptStore.put()` failure at exactly that instant (e.g.
# generation_attempt_store_from_env()'s Postgres path hitting a DATABASE_URL outage) used to raise a raw
# exception straight out of `register_generated_subsystem()`, which broke every "a handler must NEVER
# raise" continuation-dispatch contract downstream in packages/agents/openrouter_provider.py and hid the
# already-live registry mutation from every caller (see generated_registration.py's own comment on the
# fix, right above the guarded `resolved_store.put(attempt)` call inside `_finish`).


class _StorePutAlwaysRaises:
    """A GenerationAttemptStore stand-in whose put() always raises -- simulates
    generation_attempt_store_from_env()'s Postgres path hitting a DATABASE_URL outage at exactly the
    wrong instant (the reviewer's own repro)."""

    def put(self, attempt):
        raise RuntimeError("simulated DB outage on put()")

    def get(self, attempt_id):
        return None

    def list(self, *, project_id=None, limit=100):
        return []


@pytest.mark.needs_kernel
@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_corpus_store_put_failure_after_full_acceptance_does_not_raise_and_still_registers(
    tmp_path, _clean_registry, caplog,
):
    """The dangerous half of the repro: a candidate that passes all four floors must still come back as
    a normal, accepted RegistrationResult -- never a raw exception -- even when the corpus-store write
    fails immediately after the module is already live. The registry/filesystem mutation is real and
    must not be silently hidden by the store failure -- only accurately reported (and logged loudly, so
    the outage is visible even though the corpus row itself could not be captured)."""
    import logging

    name = "gen_test_store_put_failure_2026"
    candidate = _candidate(name, _GOOD_BOX_BUILD_CODE, _GOOD_BOX_PARAMS)

    with caplog.at_level(logging.ERROR, logger="packages.subsystems.generated_registration"):
        result = register_generated_subsystem(
            candidate, store=_StorePutAlwaysRaises(), generated_dir=tmp_path)

    assert result.accepted is True
    assert result.outcome == "registered"
    assert result.attempt_id  # still populated even though the store never got the row
    assert result.model == _MODEL_ID
    assert result.sha256

    # the registry/filesystem mutation genuinely happened -- this is exactly what makes the bug
    # dangerous: it must not be silently hidden by the store failure, only accurately reported.
    model = get_subsystem_model(name)
    assert model.name == name
    assert (tmp_path / f"{name}.py").exists()

    # the outage is logged, not silently swallowed
    assert any("GenerationAttemptStore.put() failed" in r.message for r in caplog.records)
    assert any(name in r.message for r in caplog.records)


def test_corpus_store_put_failure_on_a_rejected_outcome_also_does_not_raise(tmp_path, _clean_registry):
    """Same fix, REJECTED-outcome side: `_finish()` is the identical closure for every outcome (not
    just 'registered'), so a store.put() failure while recording a floor-4 BUILD_ERROR rejection must
    also come back as a normal RegistrationResult, never a raw exception."""
    candidate = _candidate("gen_test_store_put_failure_rejected_2026", _RAISER_BUILD_CODE)

    result = register_generated_subsystem(
        candidate, store=_StorePutAlwaysRaises(), generated_dir=tmp_path)

    assert result.accepted is False
    assert result.outcome == "rejected"
    assert result.rejected_floor == FLOOR_SANDBOX_BUILD
    assert "phase3 test boom" in result.rejection_reason
