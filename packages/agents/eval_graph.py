"""Golden-set eval that grades the RESULTING GRAPH `stream_chat` produces — never the prose, never an
LLM-as-judge. This is the harness for the path that ACTUALLY SHIPS (`stream_chat` ->
instance_ops/connection_ops/coupling_ops/deltas -> the real rules validator in `packages.ledger.apply`
-> the resulting instance tree), as opposed to `packages/agents/eval.py`'s original Phase-0 harness,
which only ever graded single-parameter `propose_delta` output against `SKIN`/`RIB`.

Grading philosophy (mirrors this codebase's existing "LLM-as-judge is never used for a gate"
discipline — see the original `eval.py` module docstring): every `check` here is an EXACT structural
comparison against the resulting ledger/proposal/events — never a second model call, never a fuzzy
text-similarity score.

Two ways to exercise a `GraphEvalCase`:
  - `run_case_offline` — a deterministic FAKE `stream_post` (same injection seam
    `OpenRouterDeltaProvider` already exposes for `test_openrouter_provider.py`) stands in for the
    model, replaying `case.fixture_tool_call` verbatim. Zero network, zero API key. This is what CI
    runs on every PR — since the fixture is fully deterministic, a failure here is a REAL regression
    in `packages.ledger.apply`/`packages.ledger.schema`/`packages.subsystems`, never model noise.
  - `run_case_live` — the SAME case's `prompt` is sent to a REAL injected `LLMProvider`-shaped object
    (anything exposing `.stream_chat(messages=..., ledger_json=...)`, e.g. a real
    `OpenRouterDeltaProvider`) and graded with the exact same `check` callable. This is where model
    NON-DETERMINISM lives — never a CI gate, only ever an accuracy number (see `eval.py`'s
    `grade_live`).

Every case is ALSO checked against one blanket, always-on invariant regardless of what `case.check`
itself asserts: the resulting graph may never contain an instance whose `subsystem_type` isn't a real,
already-registered name in `packages.subsystems.SUBSYSTEM_REGISTRY` (`_check_no_invented_subsystem_types`
below) — the single HARD gate the task names as non-negotiable. See
`test_never_invents_a_subsystem_type_is_a_hard_gate` in `tests/backend/test_agents.py` for the
dedicated adversarial case (a fixture that deliberately tries to add `"satellite_body"`) pinning that
the RULES layer (not just the LLM schema) is what actually enforces this.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from packages.agents.openrouter_provider import OpenRouterDeltaProvider
from packages.couplings import RELATION_REGISTRY
from packages.ledger.apply import (
    ApplyStatus,
    apply_connection_op,
    apply_coupling_op,
    apply_delta,
    apply_instance_op,
    resolve_path,
)
from packages.ledger.deltas import DeltaProposal
from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import (
    Domains,
    GlobalConstraints,
    ManufacturingDomain,
    MasterParametricLedger,
    ProjectMetadata,
    StructureDomain,
)
from packages.subsystems import SUBSYSTEM_REGISTRY, add_instance, get_subsystem_model
from packages.subsystems.assembly_template import reconcile_all, reconcile_children
from packages.subsystems.placement import connection_issues, resolve_placements

# --- a minimal empty ledger, self-contained (no reverse dependency on packages.transport) ----------
#
# packages/transport/app.py already has an equivalent `make_core_ledger`, but importing app.py from
# here would make packages/agents depend on packages/transport — backwards from this codebase's real
# layering (transport is the top-level orchestrator that imports agents/ledger/subsystems, never the
# other way). This mirrors tests/conftest.py's own `build_ledger()` scaffold instead (same fields,
# empty `instances`).


def _empty_ledger() -> MasterParametricLedger:
    return MasterParametricLedger(
        project_metadata=ProjectMetadata(project_id="eval", version_commit="v0", branch="main", subsystem_type=""),
        global_constraints=GlobalConstraints(factor_of_safety_floor=1.5),
        domains=Domains(
            structure=StructureDomain(material_profile="PLA"),
            manufacturing=ManufacturingDomain(
                build_orientation_deg=ParameterDef(value=0.0, unit="deg", bounds=(0.0, 90.0)),
                slip_fit_clearance_mm=ParameterDef(value=0.2, unit="mm", bounds=(0.0, 1.0)),
            ),
        ),
        instances={},
    )


# --- the deterministic fake model — the SAME injection seam as test_openrouter_provider.py ---------


def make_fake_stream(*, content: str = "", tool_call_args: "dict | str | None" = None,
                      finish_reason: str = "tool_calls"):
    """Build a `stream_post` callable (`OpenRouterDeltaProvider(..., stream_post=...)`) that replays
    ONE deterministic model turn: optional prose `content`, then (unless `tool_call_args` is None) a
    single `propose_parameter_delta` tool call whose `arguments` is `tool_call_args` — a dict is
    JSON-encoded; a str is sent VERBATIM (so a case can also simulate a malformed/already-broken wire
    payload) — followed by `finish_reason`. `tool_call_args=None` simulates a pure-prose turn with no
    tool call at all."""
    args_str: Optional[str] = None
    if tool_call_args is not None:
        args_str = tool_call_args if isinstance(tool_call_args, str) else json.dumps(tool_call_args)

    def _fake_stream(*, url, headers, json):  # noqa: A002 — matches the real injected `stream_post`
                                               # seam's own kwarg name (openrouter_provider.py)
        if content:
            yield {"choices": [{"delta": {"content": content}}]}
        if args_str is not None:
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"name": "propose_parameter_delta", "arguments": args_str}}]}}]}
        yield {"choices": [{"delta": {}, "finish_reason": finish_reason}]}

    return _fake_stream


# --- replaying a DeltaProposal onto a ledger through the REAL rules validator -----------------------


def _known_subsystem_types() -> frozenset:
    return frozenset(SUBSYSTEM_REGISTRY)


def _seed_defaults(subsystem_type: str, instance_id: str, parent_id):
    from packages.subsystems.base import seed_instance
    return seed_instance(get_subsystem_model(subsystem_type), instance_id, parent_id=parent_id)


def _interfaces_of(subsystem_type: str) -> frozenset:
    try:
        return frozenset(i.name for i in get_subsystem_model(subsystem_type).interfaces)
    except KeyError:
        return frozenset()


def _inputs_of(relation: str) -> frozenset:
    rel = RELATION_REGISTRY.get(relation)
    return frozenset(rel.inputs) if rel is not None else frozenset()


@dataclass
class OpOutcomeLog:
    """Every `apply_*` outcome produced while replaying one proposal, kept in the SAME order
    `packages/frontend/src/chat/Chat.tsx` actually applies a turn's ops (instance_ops -> connection_ops
    -> coupling_ops -> deltas) — so this harness grades the real production apply order, not an
    arbitrary one chosen for the test."""

    instance: list = field(default_factory=list)
    connection: list = field(default_factory=list)
    coupling: list = field(default_factory=list)
    delta: list = field(default_factory=list)


def apply_proposal(ledger: MasterParametricLedger, proposal: DeltaProposal) -> tuple[MasterParametricLedger, OpOutcomeLog]:
    """Replay one `DeltaProposal` onto `ledger` through the REAL rules validator
    (`packages.ledger.apply`), wired EXACTLY like `packages/transport/app.py`'s REST endpoints, in the
    SAME order the frontend applies a turn's ops: instance_ops, connection_ops, coupling_ops, deltas.
    `feature_ops`/`fit_ops`/`join_annotation_ops` are out of scope for this harness — they need a real
    geometry build (`needs_kernel`); none of the golden cases in `eval.py` need them."""
    log = OpOutcomeLog()
    for op in proposal.instance_ops:
        ledger, outcome = apply_instance_op(ledger, op, _known_subsystem_types(),
                                             seed_defaults=_seed_defaults, reconcile=reconcile_children)
        log.instance.append(outcome)
    for op in proposal.connection_ops:
        ledger, outcome = apply_connection_op(ledger, op, _interfaces_of)
        log.connection.append(outcome)
    for op in proposal.coupling_ops:
        ledger, outcome = apply_coupling_op(ledger, op, frozenset(RELATION_REGISTRY), _inputs_of)
        log.coupling.append(outcome)
    for delta in proposal.deltas:
        ledger, outcome = apply_delta(ledger, delta)
        log.delta.append(outcome)
    # Mirrors packages/transport/app.py's SessionState.ledger() -> self.log.fold(reconcile=reconcile_all):
    # by the time a real client next reads the ledger, every assembly-template instance (e.g. `table`)
    # has already converged its children against whatever THIS turn's deltas just set — so the "resulting
    # graph" this harness grades matches what a user would actually see, not a pre-reconcile snapshot.
    ledger = reconcile_all(ledger)
    return ledger, log


# --- the golden case + its run context ---------------------------------------------------------


@dataclass(frozen=True)
class GraphEvalCase:
    name: str
    prompt: str                                        # what a LIVE run sends verbatim as the user turn
    initial_instances: tuple = ()                       # ((subsystem_type, instance_id), ...) seeded
                                                         # into the ledger BEFORE the turn
    # the OFFLINE fixture: a deterministic stand-in for "what a correctly-behaving model's tool call
    # looks like" for `prompt` against `initial_instances`. Replayed by run_case_offline — NEVER used
    # for live grading (that sends `prompt` to a real model instead).
    fixture_content: str = ""
    fixture_tool_call: object = None                    # dict | str | None (None = no tool call at all)
    fixture_finish_reason: str = "tool_calls"
    # runs against the RESULTING GRAPH (+ the raw DeltaProposal + the raw stream_chat events) — never
    # prose. Returns a list of human-readable failure strings; [] = pass.
    check: Callable[["GraphCaseContext"], list] = field(default=lambda ctx: [])


@dataclass
class GraphCaseContext:
    case: GraphEvalCase
    initial_ledger: MasterParametricLedger
    final_ledger: MasterParametricLedger
    events: list
    proposal: Optional[DeltaProposal]
    op_log: OpOutcomeLog


def _build_initial_ledger(case: GraphEvalCase) -> MasterParametricLedger:
    ledger = _empty_ledger()
    for subsystem_type, instance_id in case.initial_instances:
        ledger = add_instance(ledger, subsystem_type, instance_id)
    return ledger


def run_case(case: GraphEvalCase, provider) -> GraphCaseContext:
    """Drive `case` through a REAL `stream_chat` call on `provider` (whatever provider — fake or
    live), then replay whatever proposal comes back through the REAL rules validator. `provider` only
    needs to expose `.stream_chat(messages=..., ledger_json=...)` (both `OpenRouterDeltaProvider` and
    any test double built the same way satisfy this)."""
    ledger = _build_initial_ledger(case)
    events = list(provider.stream_chat(messages=[{"role": "user", "content": case.prompt}],
                                        ledger_json=ledger.model_dump_json()))
    proposal = next((payload for kind, payload in reversed(events) if kind == "proposal"), None)
    if proposal is not None:
        final_ledger, op_log = apply_proposal(ledger, proposal)
    else:
        final_ledger, op_log = ledger, OpOutcomeLog()
    return GraphCaseContext(case=case, initial_ledger=ledger, final_ledger=final_ledger,
                            events=events, proposal=proposal, op_log=op_log)


def run_case_offline(case: GraphEvalCase) -> GraphCaseContext:
    """Run `case` fully offline: `case.fixture_tool_call` stands in for the model, via the SAME
    `stream_post` injection seam `test_openrouter_provider.py` already uses. No network, no API key."""
    stream_post = make_fake_stream(content=case.fixture_content, tool_call_args=case.fixture_tool_call,
                                    finish_reason=case.fixture_finish_reason)
    provider = OpenRouterDeltaProvider(api_key="x", stream_post=stream_post)
    return run_case(case, provider)


def run_case_live(case: GraphEvalCase, provider) -> GraphCaseContext:
    """Run `case.prompt` against a REAL provider (e.g. a real `OpenRouterDeltaProvider()` reading
    `OPENROUTER_API_KEY`) — for reporting a quality/accuracy NUMBER only, never a CI gate (model output
    is non-deterministic)."""
    return run_case(case, provider)


# --- the one ALWAYS-ON, blanket hard invariant --------------------------------------------------


def _check_no_invented_subsystem_types(ctx: GraphCaseContext) -> list:
    """The single non-negotiable hard gate (task item 1): the resulting graph may never contain an
    instance whose subsystem_type isn't a real, already-registered SUBSYSTEM_REGISTRY name — checked
    on EVERY case's resulting ledger, regardless of what that case's own `check` asserts."""
    bad = [f"{iid}={inst.subsystem_type!r}" for iid, inst in ctx.final_ledger.instances.items()
           if inst.subsystem_type not in SUBSYSTEM_REGISTRY]
    if bad:
        return [f"invented subsystem_type(s) present in the resulting graph: {bad}"]
    return []


# --- reusable graph assertions (composable via all_of) -------------------------------------------


def all_of(*checks: Callable[[GraphCaseContext], list]) -> Callable[[GraphCaseContext], list]:
    def _check(ctx: GraphCaseContext) -> list:
        out: list = []
        for c in checks:
            out.extend(c(ctx))
        return out
    return _check


def added_types(ctx: GraphCaseContext) -> dict:
    """subsystem_type -> count of instances present in the FINAL ledger but absent from the INITIAL
    one — i.e. what THIS turn actually added, excluding any pre-seeded `initial_instances`."""
    initial_ids = set(ctx.initial_ledger.instances)
    counts: dict = {}
    for iid, inst in ctx.final_ledger.instances.items():
        if iid in initial_ids:
            continue
        counts[inst.subsystem_type] = counts.get(inst.subsystem_type, 0) + 1
    return counts


def expect_types(*, exact: Optional[set] = None, min_counts: Optional[dict] = None):
    """Task item 2 (correct part types + roughly correct counts): `exact` is the full set of
    subsystem_types this turn's add_instance ops must touch (no extra types, none invented);
    `min_counts` lower-bounds a per-type count (≥, not exact — "roughly correct")."""
    def _check(ctx: GraphCaseContext) -> list:
        got = added_types(ctx)
        out = []
        if exact is not None and set(got) != exact:
            out.append(f"expected added subsystem_types {sorted(exact)}, got {sorted(got)}")
        for t, n in (min_counts or {}).items():
            if got.get(t, 0) < n:
                out.append(f"expected at least {n}x {t!r} added, got {got.get(t, 0)}")
        return out
    return _check


def expect_clarify():
    """Task item 3 (clarify vs. guess): a clarification with NO accompanying ops — asking is the
    whole point, not a half-guess alongside it."""
    def _check(ctx: GraphCaseContext) -> list:
        p = ctx.proposal
        out = []
        if p is None or p.request_clarification is None:
            out.append("expected request_clarification to be set")
            return out
        if p.deltas or p.instance_ops or p.connection_ops or p.coupling_ops:
            out.append("expected NO deltas/instance_ops/connection_ops/coupling_ops alongside a "
                        "clarification (a half-guess defeats the point of asking)")
        return out
    return _check


def expect_no_proposal_and_error(substr: str = ""):
    """Task item 5's failure-mode check: a malformed wire shape must be rejected WHOLESALE (no
    partial/silent apply of the good parts alongside the bad field) — never a proposal event."""
    def _check(ctx: GraphCaseContext) -> list:
        out = []
        if ctx.proposal is not None:
            out.append("expected the malformed wire shape to be rejected wholesale (no proposal), "
                        "got one anyway")
        errors = [msg for kind, msg in ctx.events if kind == "error"]
        if not errors:
            out.append("expected an ('error', ...) event, got none")
        elif substr and not any(substr in e for e in errors):
            out.append(f"expected an error containing {substr!r}, got {errors}")
        return out
    return _check


def expect_no_new_instances():
    def _check(ctx: GraphCaseContext) -> list:
        got = added_types(ctx)
        if got:
            return [f"expected no new instances, got {got}"]
        return []
    return _check


def expect_delta_applied(target_node: str, expected_value):
    def _check(ctx: GraphCaseContext) -> list:
        pd = resolve_path(ctx.final_ledger, target_node)
        if pd is None:
            return [f"{target_node} did not resolve to a ParameterDef in the resulting graph"]
        if pd.value != expected_value:
            return [f"{target_node} = {pd.value!r}, expected {expected_value!r}"]
        return []
    return _check


def expect_instance_params(instance_id: str, expected: dict):
    """Task item 6 (a sized new part, not left at generic catalog defaults)."""
    def _check(ctx: GraphCaseContext) -> list:
        inst = ctx.final_ledger.instances.get(instance_id)
        if inst is None:
            return [f"expected instance {instance_id!r} to exist in the resulting graph"]
        out = []
        for name, val in expected.items():
            pd = inst.params.get(name)
            if pd is None:
                out.append(f"{instance_id}.{name} missing from the resulting graph")
            elif pd.value != val:
                out.append(f"{instance_id}.{name} = {pd.value!r}, expected {val!r}")
        return out
    return _check


def expect_recovered_smuggled_deltas(instance_id: str, keys: set):
    """Task item 4: a dimension smuggled directly onto an add_instance op must be recovered into the
    SIBLING `deltas` list (never left on the op — InstanceOp's own extra="forbid" already guarantees
    that structurally for anything that survived construction), targeting
    `instances.<id>.params.<key>`."""
    def _check(ctx: GraphCaseContext) -> list:
        if ctx.proposal is None:
            return ["expected a recovered proposal (smuggled-param repair should still produce one)"]
        got = {d.target_node for d in ctx.proposal.deltas
               if d.target_node.startswith(f"instances.{instance_id}.params.")}
        want = {f"instances.{instance_id}.params.{k}" for k in keys}
        if got != want:
            return [f"expected recovered deltas {sorted(want)}, got {sorted(got)}"]
        op = next((o for o in ctx.proposal.instance_ops if o.instance_id == instance_id), None)
        if op is None:
            return [f"add_instance for {instance_id!r} missing from the recovered proposal"]
        return []
    return _check


def expect_connected(a_instance: str, a_interface: str, b_instance: str, b_interface: str):
    """Task item 7: connection-graph topology (not a hand-computed position) was actually used, AND
    the mate solver (`packages.subsystems.placement`) can actually resolve + validate it."""
    def _check(ctx: GraphCaseContext) -> list:
        led = ctx.final_ledger
        wanted = {(a_instance, a_interface), (b_instance, b_interface)}
        match = next((c for c in led.connections
                      if {(c.a.instance_id, c.a.interface), (c.b.instance_id, c.b.interface)} == wanted),
                     None)
        out = []
        if match is None:
            out.append(f"expected a connection {a_instance}.{a_interface} <-> {b_instance}.{b_interface}")
            return out
        placements = resolve_placements(led)
        if a_instance not in placements and b_instance not in placements:
            out.append("neither endpoint got a mate-solved placement — connection topology wasn't "
                        "actually used")
        issues = connection_issues(led)
        if issues:
            out.append(f"connection_issues found problems: {issues}")
        return out
    return _check


def expect_no_hand_computed_position(instance_id: str):
    """Task item 7's negative half: the add_instance for `instance_id` must leave x/y/z UNSET —
    connection_ops (not a hand-computed transform) is what should place it."""
    def _check(ctx: GraphCaseContext) -> list:
        op = next((o for o in (ctx.proposal.instance_ops if ctx.proposal else [])
                   if o.instance_id == instance_id and o.op == "add_instance"), None)
        if op is None:
            return [f"no add_instance for {instance_id!r} found in the proposal"]
        if op.x_mm is not None or op.y_mm is not None or op.z_mm is not None:
            return [f"{instance_id} was given an explicit position ({op.x_mm}, {op.y_mm}, {op.z_mm}) "
                    f"instead of relying on connection_ops"]
        return []
    return _check


def expect_instance_op_rejected():
    def _check(ctx: GraphCaseContext) -> list:
        rejected = [o for o in ctx.op_log.instance if o.status is ApplyStatus.REJECTED]
        if not rejected:
            return ["expected a REJECTED instance_ops outcome, got none"]
        return []
    return _check


def expect_removed(instance_id: str):
    def _check(ctx: GraphCaseContext) -> list:
        out = []
        if instance_id in ctx.final_ledger.instances:
            out.append(f"expected {instance_id!r} to be removed, still present in the resulting graph")
        applied = [o for o in ctx.op_log.instance
                   if o.status is ApplyStatus.APPLIED and o.instance_id == instance_id]
        if not applied:
            out.append(f"expected an APPLIED remove_instance outcome for {instance_id!r}")
        return out
    return _check


def expect_present(instance_id: str):
    def _check(ctx: GraphCaseContext) -> list:
        if instance_id not in ctx.final_ledger.instances:
            return [f"expected {instance_id!r} to still be present in the resulting graph"]
        return []
    return _check


def expect_moved(instance_id: str, x_mm: float, y_mm: float, z_mm: float):
    def _check(ctx: GraphCaseContext) -> list:
        inst = ctx.final_ledger.instances.get(instance_id)
        if inst is None or inst.transform is None:
            return [f"expected {instance_id!r} to carry a transform after move_instance"]
        t = inst.transform
        if (t.x_mm, t.y_mm, t.z_mm) != (x_mm, y_mm, z_mm):
            return [f"expected {instance_id!r} at ({x_mm}, {y_mm}, {z_mm}), got "
                    f"({t.x_mm}, {t.y_mm}, {t.z_mm})"]
        return []
    return _check


# --- aggregate grading ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    case: GraphEvalCase
    ctx: GraphCaseContext
    failures: list

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass
class GraphEvalReport:
    total: int
    passed: int
    results: list = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _grade(cases, run_fn: Callable[[GraphEvalCase], GraphCaseContext]) -> GraphEvalReport:
    results = []
    passed = 0
    for case in cases:
        ctx = run_fn(case)
        failures = _check_no_invented_subsystem_types(ctx) + list(case.check(ctx))
        if not failures:
            passed += 1
        results.append(CaseResult(case=case, ctx=ctx, failures=failures))
    return GraphEvalReport(total=len(cases), passed=passed, results=results)


def grade_offline(cases) -> GraphEvalReport:
    """Deterministic, offline, no-network grading — CI runs this on every PR. A failure here is a real
    plumbing regression (the fixtures are hand-authored to represent CORRECT model behavior), never
    model non-determinism."""
    return _grade(cases, run_case_offline)


def grade_live(provider, cases) -> GraphEvalReport:
    """Grade `cases` against a REAL model via `provider`. Reports an accuracy NUMBER only — never a CI
    gate (design constraint: stochastic live-model quality must never be a hard-failing gate)."""
    return _grade(cases, lambda case: run_case_live(case, provider))
