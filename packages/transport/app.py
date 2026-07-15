"""FastAPI app tying the backbone together: the two-plane WS + export REST.

Tier 0 only (in-process, closed-form): a slider mutation is rules-validated, committed to the event
log if it changes state, and answered with a cascade + analytic telemetry — or a NACK. The kernel and
solver tiers live behind the Truth Plane and are out of this hot path by design.
"""

from __future__ import annotations

import contextvars
import dataclasses
import json
import os
import secrets
import tempfile

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.background import BackgroundTask

from packages.agents.strategic import StrategicAgent
from packages.disciplines import all_discipline_findings
from packages.subsystems import (
    SUBSYSTEM_REGISTRY,
    add_instance,
    geometry_paths,
    get_subsystem,
    get_subsystem_model,
    remove_instance,
)
from packages.subsystems.assembly_template import reconcile_all, reconcile_children
from packages.subsystems.base import seed_instance
from packages.ledger.apply import apply_delta, apply_feature_op, apply_instance_op
from packages.ledger.bom import BOM, Component, ComponentKind, material
from packages.ledger.deltas import FeatureOp, InstanceOp, ParameterDelta
from packages.ledger.events import EventLog
from packages.ledger.derived_resolver import latest_verdict, ledger_with_derived
from packages.ledger.fingerprint import fingerprint
from packages.ledger.gates import evaluate_export_gates
from packages.ledger.requirements import VerificationMatrix
from packages.truth_plane.analysis import analyze_in_subprocess, optimize_in_subprocess  # module-level for monkeypatch
from packages.truth_plane.verdict_store import InMemoryJobStatusStore, InMemoryVerdictStore
from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import (
    Domains,
    GlobalConstraints,
    ManufacturingDomain,
    MasterParametricLedger,
    ProjectMetadata,
    StructureDomain,
    ThermalDomain,
)  # StructureDomain now holds only material_profile (Phase D)
from packages.transport.protocol import (
    CascadeEffect,
    CascadeUpdate,
    MutationApplied,
    MutationRejected,
    ParamMutationRequest,
    TelemetryDelta,
)

_PROFILE = "PLA"
_TS = "2026-06-28T00:00:00Z"


def _pd(value, lo, hi, lock=LockState.DYNAMIC):
    return ParameterDef(value=value, unit="mm", bounds=(lo, hi), lock_state=lock)


def _instance_id_from_target(target_node: str) -> str | None:
    """`instances.<id>.params.<name>` -> `<id>`; anything else (a discipline path) -> None. A
    mutation's target already encodes which instance it addresses — this lets `mutate()` dispatch to
    the RIGHT instance's subsystem invariants without depending on session `active_instance_id`."""
    parts = target_node.split(".")
    if len(parts) == 4 and parts[0] == "instances" and parts[2] == "params":
        return parts[1]
    return None


def make_core_ledger(subsystem_type: str = "bracket") -> MasterParametricLedger:
    """The shared core: material discipline + universal manufacturing + thermal, with an empty
    instance tree. A subsystem's geometry params land in that tree via `add_instance`/
    `apply_instance_op` (which seed defaults + reconcile any assembly-template children) — never
    here; this only builds the cross-cutting scaffolding every project needs regardless of what
    (if anything) has been added to it yet."""
    return MasterParametricLedger(
        project_metadata=ProjectMetadata(project_id="demo", version_commit="v0", branch="main",
                                         subsystem_type=subsystem_type),
        global_constraints=GlobalConstraints(factor_of_safety_floor=1.5),
        domains=Domains(
            structure=StructureDomain(material_profile=_PROFILE),
            manufacturing=ManufacturingDomain(
                build_orientation_deg=ParameterDef(value=0.0, unit="deg", bounds=(0.0, 90.0)),
                slip_fit_clearance_mm=_pd(0.2, 0.0, 1.0),
            ),
            thermal=ThermalDomain(
                operating_temp_c=ParameterDef(value=25.0, unit="degC", bounds=(-40.0, 200.0)),
                power_dissipation_w=ParameterDef(value=0.0, unit="W", bounds=(0.0, 500.0)),
            ),
        ),
    )


def make_demo_ledger() -> MasterParametricLedger:
    # 2026-07-04: a project starts as an empty workspace, not seeded with a default "bracket" — the
    # ledger schema already supports `instances={}` (Phase G), so this is just `make_core_ledger()`
    # with no subsystem layered on top. The first instance (whichever the user/copilot adds via
    # instance_ops or the outliner's "+") becomes the root — see `resolve_instance_parent`.
    return make_core_ledger(subsystem_type="")


_DEMO_BOM = BOM([
    Component("cellA", 70.0, (0.0, 0.0, 0.0), ComponentKind.POWER),
    Component("cellB", 70.0, (100.0, 0.0, 0.0), ComponentKind.POWER),
    Component("payload", 10.0, (200.0, 0.0, 0.0), ComponentKind.PAYLOAD),
])


def _render_geometry(ledger: MasterParametricLedger, active_instance_id: str | None):
    """The geometry `/mesh` and `/export/step` show. Once a project holds MORE THAN ONE instance,
    this is the whole assembly (every instance composed via its Transform — see
    packages/subsystems/assembly.py); a single-instance project (the common case, and every project
    before Item 3) gets exactly the active instance's own geometry, byte-for-byte the same as before
    — zero behavior change for that case. Returns None if there is no geometry to show."""
    if len(ledger.instances) > 1:
        from packages.subsystems.assembly import render_assembly
        return render_assembly(ledger)
    inst = ledger.instances.get(active_instance_id)
    if inst is None:
        return None
    sub = get_subsystem(inst.subsystem_type)
    if sub.geometry_builder is None:
        return None
    return sub.geometry_builder(ledger, inst.id)


def _telemetry(ledger: MasterParametricLedger, instance_id: str | None = None) -> TelemetryDelta:
    s = ledger.domains.structure
    mat = material(s.material_profile)
    bom_mass = _DEMO_BOM.total_mass_g()
    bom_cg = _DEMO_BOM.cg_mm()
    if not ledger.instances:
        # empty workspace — nothing structural to weigh/print yet; BOM (batteries/payload) alone is real.
        total, cg, vol_for_print = bom_mass, tuple(round(v, 3) for v in bom_cg), 0.0
    elif len(ledger.instances) > 1:
        # assembly-wide (2026-07-03): sum every instance's mass; weight CG by each instance's
        # WORLD-SPACE offset (packages/subsystems/assembly.py) instead of reporting the active part
        # alone. This is the "next increment" the Item 3 MVP explicitly deferred.
        from packages.subsystems.assembly import instance_world_offsets
        offsets = instance_world_offsets(ledger)
        structural_g = 0.0
        moment = [bom_mass * bom_cg[0], bom_mass * bom_cg[1], bom_mass * bom_cg[2]]
        total_vol = 0.0
        for iid, inst in ledger.instances.items():
            sub = get_subsystem(inst.subsystem_type)
            vol = sub.volume_mm3(ledger, iid) if sub.volume_mm3 is not None else 0.0
            total_vol += vol
            part_mass = mat.density_g_per_mm3 * vol
            structural_g += part_mass
            ox, oy, oz = offsets.get(iid, (0.0, 0.0, 0.0))
            moment[0] += part_mass * ox
            moment[1] += part_mass * oy
            moment[2] += part_mass * oz
        total = bom_mass + structural_g
        cg = tuple(round(m / total, 3) if total else 0.0 for m in moment)
        vol_for_print = total_vol
    else:
        # exactly one instance in the file (2026-07-04: parts are a flat set, no root) — resolve it
        # by the given id if it actually matches, else it's just THE instance.
        inst = ledger.instances.get(instance_id) if instance_id is not None else None
        if inst is None:
            inst = next(iter(ledger.instances.values()))
        sub = get_subsystem(inst.subsystem_type)
        vol_for_print = sub.volume_mm3(ledger, inst.id) if sub.volume_mm3 is not None else 0.0
        structural_g = mat.density_g_per_mm3 * vol_for_print
        total = bom_mass + structural_g
        cg = tuple(round(v, 3) for v in bom_cg)
    from packages.disciplines.cost import cost_usd
    return TelemetryDelta(
        total_mass_g=round(total, 3),
        cg_mm=cg,
        estimated_print_time_s=round(vol_for_print / 5.0, 1),
        estimated_cost_usd=round(cost_usd(ledger), 2),  # analytic — Cost discipline
    )


class ProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str
    api_key: str | None = None   # user-supplied OpenRouter key (else no LLM)
    model: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[dict]         # [{role, content}, ...] conversation history
    api_key: str | None = None
    model: str | None = None


class GoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str                    # natural-language design goal -> a verification matrix (TARGETS only)


class AddInstanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subsystem_type: str           # which part type this new instance is (key into SUBSYSTEM_REGISTRY)
    instance_id: str | None = None  # auto-generated if omitted
    parent_id: str | None = None    # omitted -> top-level part (the common case); real parenting is
                                     # opt-in, never assumed


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _param_label(path: str) -> str:
    seg = path.split(".")[-1]
    for suffix in ("_mm", "_deg", "_c", "_w"):
        if seg.endswith(suffix):
            seg = seg[: -len(suffix)]
            break
    return seg.replace("_", " ").strip().capitalize()


def _make_verdict_store():
    if os.environ.get("DATABASE_URL"):
        from packages.ledger.event_store_pg import PgVerdictStore
        return PgVerdictStore.from_env()
    return InMemoryVerdictStore()


def _make_status_store():
    # a queued /analyze or /optimize job's progress must be readable by the WEB process even though
    # the actor body runs in a separate WORKER process (2026-07-15 fix — packages/truth_plane/jobs.py's
    # module docstring) — same in-mem/Postgres split as the verdict store, for the same reason.
    if os.environ.get("DATABASE_URL"):
        from packages.ledger.event_store_pg import PgJobStatusStore
        return PgJobStatusStore.from_env()
    return InMemoryJobStatusStore()


def _make_event_log(project_id: str):
    if os.environ.get("DATABASE_URL"):
        from packages.ledger.event_store_pg import PgEventStore
        # project_id scopes the shared Postgres `events` table per file (2026-07-15 — the table used
        # to have NO scoping column at all, so every file/session/tenant folded one shared global
        # stream; see event_store_pg.py's module docstring).
        return PgEventStore.from_env(project_id=project_id)
    return EventLog()


class FileState:
    """Everything that makes up ONE design file: its own event log, goal matrix, and which instance
    is currently being edited (2026-07-04: files, not a single global project — think browser tabs,
    each an independent design). `verdict_store` and `strategic` are SHARED across every file in the
    session (injected, not owned) — the verdict store already scopes its own data by a project-id
    key, so handing it `file_id` isolates verdicts per file for free; `strategic` is a stateless
    heuristic parser with nothing per-file to hold."""

    def __init__(self, file_id: str, name: str, verdict_store, strategic: StrategicAgent) -> None:
        self.file_id = file_id
        self.name = name
        self.log = _make_event_log(self.file_id)
        if not self.log.events():  # fresh file -> seed genesis; else reuse the durable history
            self.log.append_genesis(make_demo_ledger(), actor="system", ts=_TS)
        self.verdict_store = verdict_store
        self.strategic = strategic
        # the user's GOAL as a verification matrix — the strategic layer sets TARGETS (never values);
        # compliance is judged later against real solver / geometry metrics. Empty until a goal is stated.
        self.matrix: VerificationMatrix = VerificationMatrix()
        # the stated applied load (e.g. "holds 200 N") — a solver INPUT, not a checkable target, so it
        # lives outside `matrix` (see packages/agents/strategic.py's module docstring). Last-stated
        # wins, same accretion shape `merge()` uses for the matrix; None until a load is ever stated.
        self.stated_load_n: float | None = None
        # Item 3 (2026-07-03): which instance /params, /mesh, /export/step, /analyze target. Parts
        # are a flat set (2026-07-04, no root) — `None` on a fresh/empty file; `active_instance()`
        # picks one as soon as the file has any parts.
        self.active_instance_id: str | None = None

    def active_instance(self):
        """The Instance /params, /mesh, /export/step, /analyze currently target. Self-heals to
        whichever instance happens to exist if the pointer went stale (e.g. the active one was
        removed) or was never set — never raises. Returns None on an empty file."""
        led = self.ledger()
        inst = led.instances.get(self.active_instance_id) if self.active_instance_id else None
        if inst is None and led.instances:
            self.active_instance_id = next(iter(led.instances))
            inst = led.instances[self.active_instance_id]
        return inst

    def activate_instance(self, instance_id: str) -> None:
        led = self.ledger()
        if instance_id not in led.instances:
            raise KeyError(f"unknown instance id {instance_id!r}")
        self.active_instance_id = instance_id

    def note_message(self, message: str) -> None:
        # the chat is the single input: fold any stated TARGETS into the goal (no-op if none stated)
        self.matrix = self.strategic.merge(self.matrix, message)
        if (n := self.strategic.extract_load_n(message)) is not None:
            self.stated_load_n = n

    def metrics(self) -> dict[str, float | None]:
        """The live, GROUNDED metric snapshot a requirement is judged against. factor_of_safety comes
        from the resolved real-solver verdict (None == unknown == not-yet-proven, never assumed);
        mass / print-time are deterministic geometry computations (the analytic estimate, labeled)."""
        derived = self.resolved_ledger().derived
        tel = _telemetry(self.ledger(), self.active_instance_id)
        return {"factor_of_safety": derived.factor_of_safety,
                "mass_g": tel.total_mass_g,
                "print_time_s": tel.estimated_print_time_s}

    def ledger(self) -> MasterParametricLedger:
        # Resolved at read time, never persisted — same pattern as `resolved_ledger()`'s derived-value
        # resolution below. `replay()` only folds FACT events (GENESIS/PARAMETER_MUTATION/...) through
        # `apply_delta`; it has no notion of assembly-template children, so a mutation that changes an
        # assembly root's master param (e.g. table's `leg_height_mm`) would otherwise leave the child
        # instances that actually carry the geometry (top/legN) holding their stale, pre-edit values on
        # every subsequent read (render, export, metrics — not just the mutation's own response).
        # `reconcile_all` is a pure, deterministic function of ledger state (no LLM/solver), and a fast
        # no-op on an already-converged tree, so it's safe to run unconditionally on every fold.
        # Passed in AS the fold's reconcile hook (not applied once afterward) so a FEATURE_OP fact
        # targeting an assembly-template-synthesized child (e.g. "table_1_top", never itself an
        # INSTANCE_ADDED fact) sees that child already materialized by the time its own event folds —
        # otherwise `replay()`'s FEATURE_OP branch can't find the target instance yet and silently
        # drops the cut (see that branch's comment in packages/ledger/events.py).
        return self.log.fold(reconcile=reconcile_all)

    def current_params(self) -> dict[str, float]:
        """The ACTIVE instance's full param set, dotted-path keyed (generic across every subsystem —
        the solver reads whatever params that subsystem actually declares, not a fixed bracket list)."""
        inst = self.active_instance()
        if inst is None:
            return {}
        return {f"instances.{inst.id}.params.{name}": pd.value for name, pd in inst.params.items()}

    def effective_fs_floor(self) -> float:
        # the LLM sets the TARGET; everything downstream enforces it. The enforced floor is the stricter
        # of the project default and whatever the stated goal demands.
        base = self.ledger().global_constraints.factor_of_safety_floor
        goal = self.strategic.floor_fs(self.matrix)
        return max(base, goal) if goal is not None else base

    def effective_load_n(self, default: float) -> float:
        # mirrors effective_fs_floor: the solver's applied load is whatever the goal stated (2026-07-15
        # fix — previously every /analyze and /optimize call solved a hardcoded default load no matter
        # what the user actually asked for, so a "holds 200 N" goal got a real-but-wrong-load FS back).
        return self.stated_load_n if self.stated_load_n is not None else default

    def resolved_ledger(self) -> MasterParametricLedger:
        # the export gate sees `derived` resolved from the latest matching analysis verdict for the
        # ACTIVE instance's OWN params (not a hardcoded bracket list), AND the FS floor RAISED to
        # whatever the stated goal demands. Both are resolved at read time on a fresh fold; neither is
        # persisted.
        inst = self.active_instance()
        gp = geometry_paths(get_subsystem_model(inst.subsystem_type), inst.id) if inst is not None else None
        led = ledger_with_derived(self.ledger(), self.verdict_store.verdicts(self.file_id),
                                  fingerprint=fingerprint(), geometry_params=gp,
                                  instance_id=inst.id if inst is not None else None)
        floor = self.effective_fs_floor()
        if floor > led.global_constraints.factor_of_safety_floor:
            gc = led.global_constraints.model_copy(update={"factor_of_safety_floor": floor})
            led = led.model_copy(update={"global_constraints": gc})
        return led

    def signoff(self, reviewer: str) -> None:
        self.log.append_signoff(reviewer, ts=_TS)

    def mutate(self, req: ParamMutationRequest):
        led = self.ledger()
        delta = ParameterDelta(target_node=req.target_node, requested_value=req.requested_value,
                               set_lock=LockState(req.set_lock) if req.set_lock else None)
        # enforce the TARGETED instance's own subsystem invariants (bracket edge-distance, enclosure
        # cavity sanity, …) on the live slider path, on top of the general min-wall floor. The target
        # path already encodes which instance it addresses — dispatch on THAT when it names one,
        # falling back to the file's active instance for a cross-cutting param (material profile,
        # build orientation, …) that isn't itself instance-scoped.
        target_iid = _instance_id_from_target(req.target_node) or self.active_instance_id
        target_inst = led.instances.get(target_iid) if target_iid else None
        # No target instance at all (an empty file, or a cross-cutting mutation with nothing yet to
        # scope invariants to) -> nothing to validate beyond apply_delta's own bounds/lock checks.
        domain_checks = None
        cascade_rules = None
        if target_inst is not None:
            subsystem = get_subsystem(target_inst.subsystem_type)
            domain_checks = lambda ledger, _s=subsystem, _t=target_iid: _s.check_invariants(ledger, _t)  # noqa: E731
            cascade_rules = subsystem.cascades
        new, outcome = apply_delta(led, delta, domain_checks=domain_checks, cascade_rules=cascade_rules)
        if outcome.changed:
            # Assembly-template mechanism (2026-07-03): re-materialize affected children so this
            # response's OWN telemetry_delta is fresh too (not just the next `self.ledger()` read,
            # which already reconciles). Covers cascades landing on a different instance as well as
            # the direct edit — a no-op for anything that isn't an assembly-template instance.
            new = reconcile_all(new)
            # Commit cascade effects as their OWN mutation events, BEFORE the direct edit's event —
            # replay() knows nothing about cascades (and doesn't need to: it just re-folds
            # PARAMETER_MUTATION events through apply_delta with no cascade_rules). Ordering the
            # cascade first means the ledger already carries the companion value by the time the
            # direct edit itself replays, so the SAME sequence of plain mutations reconstructs
            # identical state without ever re-deriving or re-validating what already happened here.
            for c in outcome.cascades:
                self.log.append_mutation(
                    ParameterDelta(target_node=c.target, requested_value=c.new_value),
                    actor="cascade", ts=_TS)
            self.log.append_mutation(delta, actor="user", ts=_TS)
            return CascadeUpdate(
                mutations_applied=[MutationApplied(node=outcome.target, value=outcome.new_value,
                                                   old_value=outcome.old_value, status=outcome.status.value)],
                cascades_applied=[CascadeEffect(node=c.target, value=c.new_value, old_value=c.old_value,
                                                reason=c.reason) for c in outcome.cascades],
                telemetry_delta=_telemetry(new, self.active_instance_id),
            )
        return MutationRejected(target_node=outcome.target, status=outcome.status.value,
                                reason=outcome.message or outcome.status.value)


class SessionState:
    """The whole server-side session: a set of design FILES plus which one is active (2026-07-04).
    Delegates its ledger/mutate/metrics/... methods and its log/matrix/active_instance_id/project_id
    attributes to the active file, so every route below (written against what used to be a single
    global project) keeps working completely unchanged — only file management (`/files*`) is new."""

    def __init__(self) -> None:
        self.verdict_store = _make_verdict_store()   # SHARED across files, keyed per-file by file_id
        self.status_store = _make_status_store()      # SHARED — a queued job's progress, same keying
        self.strategic = StrategicAgent()             # SHARED — stateless heuristic parser
        self._next_untitled = 1
        first = self._make_file()
        self.files: dict[str, FileState] = {first.file_id: first}
        self.active_file_id: str = first.file_id

    def _make_file(self) -> FileState:
        n = self._next_untitled
        self._next_untitled += 1
        # file_id is the durable-store scoping key (PgVerdictStore.project_id, PgEventStore's
        # project_id column) — it MUST be globally unique across every session/tenant, not just
        # within this one. A per-session sequential "file_{n}" (every session's first file was
        # literally "file_1") let one tenant's cached FS verdict/optimize result satisfy another
        # tenant's request on a Postgres-backed deployment whenever both held the same default,
        # untouched geometry (2026-07-15 audit finding). `name` stays the plain sequential display
        # counter — only the storage-facing id needs the random suffix.
        return FileState(file_id=f"file_{n}_{secrets.token_urlsafe(6)}", name=f"Untitled {n}",
                         verdict_store=self.verdict_store, strategic=self.strategic)

    def active_file(self) -> FileState:
        return self.files[self.active_file_id]

    def create_file(self) -> FileState:
        f = self._make_file()
        self.files[f.file_id] = f
        self.active_file_id = f.file_id
        return f

    def open_file(self, file_id: str) -> FileState:
        if file_id not in self.files:
            raise KeyError(f"unknown file id {file_id!r}")
        self.active_file_id = file_id
        return self.files[file_id]

    def list_files(self) -> list[dict]:
        return [{"id": f.file_id, "name": f.name, "part_count": len(f.ledger().instances),
                 "is_active": fid == self.active_file_id}
                for fid, f in self.files.items()]

    # --- delegate everything else to the active file — routes below never change ------------------
    def ledger(self): return self.active_file().ledger()
    def current_params(self): return self.active_file().current_params()
    def effective_fs_floor(self): return self.active_file().effective_fs_floor()
    def effective_load_n(self, default): return self.active_file().effective_load_n(default)
    def resolved_ledger(self): return self.active_file().resolved_ledger()
    def signoff(self, reviewer): return self.active_file().signoff(reviewer)
    def mutate(self, req): return self.active_file().mutate(req)
    def metrics(self): return self.active_file().metrics()
    def active_instance(self): return self.active_file().active_instance()
    def activate_instance(self, instance_id): return self.active_file().activate_instance(instance_id)
    def note_message(self, message): return self.active_file().note_message(message)

    @property
    def log(self):
        return self.active_file().log

    @property
    def matrix(self):
        return self.active_file().matrix

    @property
    def stated_load_n(self):
        return self.active_file().stated_load_n

    @property
    def active_instance_id(self):
        return self.active_file().active_instance_id

    @active_instance_id.setter
    def active_instance_id(self, value):
        self.active_file().active_instance_id = value

    @property
    def project_id(self):
        # the verdict store / analyze-optimize job queue's scoping key — the ACTIVE file's id, so
        # queued analyze/optimize jobs and their cached verdicts never cross between files.
        return self.active_file().file_id


# --- Session isolation + auth (2026-07-15) ----------------------------------------------------------
# Before this, ONE global SessionState was shared by every client that ever hit this server — any
# browser tab, from anyone on the network, read/mutated/exported the SAME ledger, and every endpoint
# was unauthenticated. `SessionManager` now maps an opaque per-browser cookie to its OWN isolated
# SessionState; `_current_session` + `_SessionProxy` let every route body below keep referencing the
# free variable `state` completely UNCHANGED (they still do `state.ledger()`, `state.mutate(req)`, …)
# while it transparently resolves to THIS request's own session instead of one shared instance.

_current_session: "contextvars.ContextVar[SessionState]" = contextvars.ContextVar("current_session")


class _SessionProxy:
    """Forwards every attribute access to whichever SessionState `_current_session` is bound to for
    the request/connection currently executing — set by `_require_session` (REST, via a FastAPI
    dependency) or directly inside the `/ws` handler (WebSocket, which can't use `Depends`)."""

    def __getattr__(self, name):
        return getattr(_current_session.get(), name)

    def __setattr__(self, name, value):
        setattr(_current_session.get(), name, value)


state = _SessionProxy()


def _check_auth_token(headers) -> bool:
    """True if `headers` (a `Request.headers` or `WebSocket.headers` mapping — same interface) carries
    the configured shared secret via `Authorization: Bearer <token>`, OR no `AUTH_TOKEN` is configured
    at all (open — matches this app's pre-auth behavior; an operator opts into gating explicitly by
    setting the env var). Constant-time comparison against a timing side-channel on the token."""
    token = os.environ.get("AUTH_TOKEN")
    if not token:
        return True
    auth = headers.get("authorization", "")
    supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
    return secrets.compare_digest(supplied, token)


class SessionLimitReached(Exception):
    """Raised by `SessionManager` when MAX_SESSIONS is already reached and a NEW session was
    requested. The caller (the REST dependency / the /ws handler) turns this into a 503 / a WS close
    rather than silently evicting a live session out from under whoever currently holds it — an
    EARLIER version of this class evicted the oldest session FIFO-style instead, which meant any
    unauthenticated caller (the default when AUTH_TOKEN is unset) could wipe out every other active
    user's in-memory design by spamming session-minting requests (2026-07-15 audit finding, confirmed
    live: 300 anonymous requests silently evicted a real victim session with zero error/signal).
    Failing CLOSED (refuse new sessions) instead of failing OPEN (destroy old ones) is the fix."""


class SessionManager:
    """Owns every browser session's isolated `SessionState`, keyed by an opaque cookie. A NEW session
    can only be minted by a request that either supplies the configured `AUTH_TOKEN` (when one is
    set) or — when none is configured — by anyone at all, matching this app's original zero-auth
    local-dev behavior. An EXISTING session_id that already maps to a live session is trusted without
    re-checking the token; this is what lets the browser's native WebSocket API (which cannot set
    custom headers) join an already-authenticated browser session via its cookie alone.

    KNOWN LIMITATION (documented, not fixed here — out of scope for this pass; matches CLAUDE.md's
    cut-list, which excludes scale-infra): this is a single in-process dict, created fresh per
    `create_app()` call. It is NOT shared across multiple worker processes (`gunicorn -w N` /
    multiple uvicorn processes behind a load balancer with no session affinity) — a request routed to
    a different worker than the one that minted a session will not find it, and will either silently
    get a fresh empty session (AUTH_TOKEN unset) or a spurious 401/1008 (AUTH_TOKEN set, since a
    browser's WS can't re-present the token). The documented `docker compose up` deployment runs
    exactly one backend process today, so this doesn't currently bite — but it means this class
    cannot be scaled to multiple backend replicas without first moving session storage to Redis
    (already provisioned in the stack for Dramatiq) or an equivalent shared store."""

    COOKIE_NAME = "gtc_session"
    # A coarse safeguard against unbounded memory growth (e.g. many clients that never persist the
    # cookie) — NOT a real LRU/TTL policy. Sized well above any real single-operator or small-team
    # session count. Reaching it REFUSES new sessions (SessionLimitReached) rather than evicting an
    # existing one — see SessionLimitReached's docstring for why eviction was actively dangerous.
    MAX_SESSIONS = 256

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def resolve(self, session_id: str | None) -> SessionState | None:
        return self._sessions.get(session_id) if session_id else None

    def _new_session(self) -> tuple[str, SessionState]:
        if len(self._sessions) >= self.MAX_SESSIONS:
            raise SessionLimitReached(
                f"{self.MAX_SESSIONS} concurrent sessions already open — try again shortly, or set "
                f"AUTH_TOKEN to restrict who can open new sessions at all"
            )
        sid = secrets.token_urlsafe(32)
        session = SessionState()
        self._sessions[sid] = session
        return sid, session

    def get_or_create(self, session_id: str | None) -> tuple[str, SessionState, bool]:
        """Returns (session_id, session, is_new) — `is_new` tells the caller whether to set the
        cookie on its response/accept handshake."""
        existing = self.resolve(session_id)
        if existing is not None:
            return session_id, existing, False
        sid, session = self._new_session()
        return sid, session, True

    def only(self) -> SessionState:
        """Test-only escape hatch (mirrors the old `app.state.session` singleton): valid whenever
        exactly one session exists, true for every test that drives a single TestClient instance —
        its cookie jar reuses the SAME session across every call it makes."""
        if len(self._sessions) != 1:
            raise AssertionError(f"expected exactly one session, found {len(self._sessions)}")
        return next(iter(self._sessions.values()))


def create_app() -> FastAPI:
    # Overrides packages/ledger/bom.py's MATERIAL_DB / packages/disciplines/cost.py's machine rate
    # from packages/catalog (2026-07-15) if a reference-data source is configured — a no-op falling
    # back to the hardcoded defaults on any failure (see bootstrap.py's own docstring). Also called
    # from packages/truth_plane/worker.py, since analyze_geometry/cost/thermal also run in that
    # SEPARATE process, which never touches create_app().
    from packages.catalog.bootstrap import apply_to_live_app
    apply_to_live_app()

    # FastAPI's own auto-generated /docs, /redoc, /openapi.json are registered directly on `app` at
    # construction time — BEFORE `router`'s auth dependency exists, and never wrapped by it (2026-07-15
    # audit finding: these leaked the full private route/schema surface, including internal request
    # models like ProposeRequest.api_key, to an anonymous caller even with AUTH_TOKEN configured).
    # Disabled here; equivalent routes are re-added on `router` below so they inherit the SAME gate.
    app = FastAPI(title="Grounded Text-to-CAD (Tier 0)", docs_url=None, redoc_url=None, openapi_url=None)
    sessions = SessionManager()
    app.state.sessions = sessions  # test-only escape hatch — see SessionManager.only()

    async def _require_session(request: Request, response: Response) -> None:
        """FastAPI dependency attached to every REST route below except /healthz (see `router`):
        resolves THIS request's own session (isolating it from every other client's), enforcing
        AUTH_TOKEN only for a request with no existing session yet — see SessionManager's docstring.
        MUST be `async def`, not plain `def`: FastAPI runs a sync dependency via `run_in_threadpool`,
        which executes it against a COPY of the current context in a worker thread — a contextvar set
        there (`_current_session.set(...)` below) never propagates back out, so every later sync
        route handler (also threadpool-offloaded) would see an unset contextvar. An async dependency
        runs directly on the event loop in the SAME task as the request, so the mutation is visible
        to everything that runs afterward in that task — including a later threadpool-offloaded sync
        route handler, whose context copy is taken AFTER this dependency has already set it."""
        session_id = request.cookies.get(SessionManager.COOKIE_NAME)
        existing = sessions.resolve(session_id)
        if existing is None and not _check_auth_token(request.headers):
            raise HTTPException(status_code=401, detail="unauthorized — set Authorization: Bearer <AUTH_TOKEN>")
        try:
            sid, session, is_new = sessions.get_or_create(session_id)
        except SessionLimitReached as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        _current_session.set(session)
        if is_new:
            response.set_cookie(SessionManager.COOKIE_NAME, sid, httponly=True, samesite="lax")

    router = APIRouter(dependencies=[Depends(_require_session)])

    # Gated re-implementations of FastAPI's disabled default docs routes (see the docs_url=None note
    # above) — same auth dependency as every other route, since they exist ONLY on `router` too.
    @router.get("/openapi.json", include_in_schema=False)
    def openapi_schema():
        return JSONResponse(app.openapi())

    @router.get("/docs", include_in_schema=False)
    def swagger_docs():
        from fastapi.openapi.docs import get_swagger_ui_html
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Swagger UI")

    @router.get("/redoc", include_in_schema=False)
    def redoc_docs():
        from fastapi.openapi.docs import get_redoc_html
        return get_redoc_html(openapi_url="/openapi.json", title=f"{app.title} - ReDoc")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @router.get("/ledger")
    def get_ledger():
        return state.ledger().model_dump(mode="json")

    @router.get("/params")
    def params():
        # the tunable sliders for the ACTIVE INSTANCE's subsystem (its geometry params + cross-cutting
        # params) — so the UI renders the right controls for whichever part is currently selected in
        # the outliner, not always the root/first part.
        from packages.ledger.branch import iter_parameters
        from packages.ledger.nodes import BUILD_ORIENTATION, OPERATING_TEMP, POWER_DISSIPATION, SLIP_FIT
        led = state.ledger()
        inst = state.active_instance()
        if inst is None:  # empty workspace — no part to show sliders for yet
            return {"subsystem": None, "instance_id": None, "params": []}
        sub = get_subsystem(inst.subsystem_type)
        model = get_subsystem_model(inst.subsystem_type)
        relevant = (set(geometry_paths(model, inst.id))
                   | {BUILD_ORIENTATION, SLIP_FIT, OPERATING_TEMP, POWER_DISSIPATION})
        rows = []
        for path, pd in iter_parameters(led):
            if path not in relevant:
                continue
            lo, hi = pd.bounds
            rows.append({"node": path, "value": pd.value, "min": lo, "max": hi,
                         "step": 0.1 if (hi - lo) <= 15 else 1.0, "unit": pd.unit,
                         "locked": pd.is_locked, "label": _param_label(path)})
        return {"subsystem": sub.name, "instance_id": inst.id, "params": rows}

    @router.get("/subsystems")
    def list_subsystems():
        # what part types the design engine can build, + which is active now (None on an empty
        # file, or the ACTIVE instance's own type — 2026-07-04: parts are a flat set, no root to
        # read this from instead).
        inst = state.active_instance()
        return {"active": inst.subsystem_type if inst is not None else None,
                "available": [{"name": s.name, "description": s.description,
                               "disciplines": list(s.applicable_disciplines)}
                              for s in SUBSYSTEM_REGISTRY.values()]}

    # --- Files (2026-07-04) — a session can hold several independent design files, each with its
    # own parts/goal/history (think browser tabs). Replaces the old switch_subsystem/project-reset
    # mechanic entirely: picking a part type was never a separate action to begin with (it's just
    # instance_ops/`POST /instances` against whichever file is open), and "start completely over"
    # is now literally "open a new file" rather than silently wiping the one you had.

    @router.get("/files")
    def list_files():
        return {"files": state.list_files()}

    @router.post("/files")
    def create_file():
        f = state.create_file()
        return {"ok": True, "id": f.file_id, "name": f.name}

    @router.post("/files/{file_id}/open")
    def open_file(file_id: str):
        try:
            state.open_file(file_id)
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "id": file_id}

    # --- Item 3 (2026-07-03): the multi-instance outliner ---------------------------------------
    # MVP scope: add/remove/activate instances in the project's tree; editing/mesh/export/analyze
    # always target the ONE currently-active instance (state.active_instance_id). Assembly-wide
    # rendering (composing every instance via its Transform into one scene) is the deliberately
    # deferred next increment — this gives real independent-part editing (a bracket AND a standoff in
    # one project, each with its own params) without that larger lift.

    @router.get("/instances")
    def list_instances():
        # cut_feature_count + world_offset are for the outliner's detail panel (feature count) and
        # its hover-highlight marker (an anchor point in the SAME raw backend coordinate space as
        # /mesh's positions and /mesh/features' PickableFeature.point — universal across every
        # instance, unlike pickable features, which only exist for instances with a tagged sub-part).
        from packages.subsystems.assembly import instance_world_offsets
        led = state.ledger()
        active_id = state.active_instance_id
        offsets = instance_world_offsets(led) if led.instances else {}
        return {"instances": [{"id": iid, "subsystem_type": inst.subsystem_type,
                               "parent_id": inst.parent_id, "is_active": iid == active_id,
                               "cut_feature_count": len(inst.cut_features),
                               "world_offset": list(offsets.get(iid, (0.0, 0.0, 0.0)))}
                              for iid, inst in led.instances.items()]}

    @router.post("/instances")
    def create_instance(req: AddInstanceRequest):
        led = state.ledger()
        instance_id = req.instance_id
        if instance_id is None:
            n = 1
            while f"{req.subsystem_type}_{n}" in led.instances:
                n += 1
            instance_id = f"{req.subsystem_type}_{n}"
        try:
            # reuse add_instance's validation (unknown subsystem / duplicate id) and its
            # seeded-defaults computation; extract the resulting Instance and append it as an
            # INCREMENTAL fact (not a wipe+regenesis) so prior mutation/signoff history survives.
            new_led = add_instance(led, req.subsystem_type, instance_id, parent_id=req.parent_id)
        except (KeyError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        state.log.append_instance_added(new_led.instances[instance_id], actor="user", ts=_TS)
        state.active_instance_id = instance_id  # the newly-added part becomes the one being edited
        return {"ok": True, "instance_id": instance_id}

    @router.delete("/instances/{instance_id}")
    def delete_instance(instance_id: str):
        led = state.ledger()
        try:
            # remove_instance validates (any instance with children is refused) before we touch
            # the log — same reuse pattern as create_instance above.
            remove_instance(led, instance_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        state.log.append_instance_removed(instance_id, actor="user", ts=_TS)
        if state.active_instance_id == instance_id:  # the active instance just got removed -> fall
            # back to whatever's left (None if the file is now empty) — no root to fall back to
            state.active_instance_id = next(iter(state.ledger().instances), None)
        return {"ok": True}

    @router.post("/instances/{instance_id}/activate")
    def activate_instance(instance_id: str):
        try:
            state.activate_instance(instance_id)
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "instance_id": instance_id}

    # --- FeatureOp: AI-proposed hole/pocket/slot cuts (2026-07-04) --------------------------------
    # Mirrors POST /instances above, not the WS mutation path: a feature op is a discrete, human-
    # accepted action (per packages/agents/CLAUDE.md's "a tool call is an AI-PROPOSED diff; a
    # separate explicit human accept commits it" hard rule) rather than a 30 Hz slider-release
    # stream, so REST fits this codebase's existing WS-vs-REST split better than extending the WS
    # protocol. The client re-POSTs the EXACT FeatureOp object it received in the /chat "proposal"
    # SSE event (see packages/ledger/deltas.py::FeatureOp) once the user clicks accept.

    @router.post("/feature_ops")
    def create_feature_op(op: FeatureOp):
        led = state.ledger()  # already reconciled — assembly-template children (e.g. "table_1_top")
                              # exist as real instance ids here even though they aren't INSTANCE_ADDED facts

        def build_part(ledger: MasterParametricLedger, instance_id: str):
            inst = ledger.instances.get(instance_id)
            if inst is None:
                return None
            sub = get_subsystem(inst.subsystem_type)
            if sub.geometry_builder is None:
                return None
            return sub.geometry_builder(ledger, instance_id)

        new_led, outcome = apply_feature_op(led, op, build_part=build_part)
        if outcome.changed:
            # log as an event-sourced FACT (the resolved CutFeature, not the raw op) so replay/undo
            # reconstruct cut_features from the log alone — see EventLog.append_feature_op.
            state.log.append_feature_op(op.op, outcome.instance_id, outcome.feature, actor="user", ts=_TS)
        return {
            "ok": outcome.changed,
            "status": outcome.status.value,
            "instance_id": outcome.instance_id,
            "feature": outcome.feature.model_dump(mode="json") if outcome.feature is not None else None,
            "message": outcome.message,
        }

    # --- InstanceOp: AI-proposed assembly composition (add/remove/move an instance) (2026-07-04) ----
    # Same "propose then explicit accept" REST shape as /feature_ops above, for the same reason (a
    # tool call is an AI-PROPOSED diff; a separate explicit human accept commits it). The ledger-side
    # mutation is IDENTICAL to what POST /instances / DELETE /instances/{id} (the original outliner
    # endpoints) already do, so this reuses their exact `append_instance_added`/`append_instance_removed`
    # event-sourced logging path rather than inventing a parallel INSTANCE_OP fact kind for the same
    # effect — one event type per real ledger mutation. `move_instance` (2026-07-05) is a third sibling
    # branch: repositioning/reorienting an ALREADY-PLACED instance, logged via `append_instance_moved`.

    @router.post("/instance_ops")
    def create_instance_op(op: InstanceOp):
        led = state.ledger()

        def seed_defaults(subsystem_type: str, instance_id: str, parent_id):
            return seed_instance(get_subsystem_model(subsystem_type), instance_id, parent_id=parent_id)

        _, outcome = apply_instance_op(
            led, op, frozenset(SUBSYSTEM_REGISTRY),
            seed_defaults=seed_defaults, reconcile=reconcile_children,
        )
        if outcome.changed:
            if op.op == "add_instance":
                state.log.append_instance_added(outcome.instance, actor="user", ts=_TS)
                state.active_instance_id = outcome.instance_id  # mirror POST /instances' behavior
            elif op.op == "move_instance":
                # Use the RESOLVED new transform from `outcome.instance` (apply_instance_op already
                # computed it correctly, including "preserve current rotation if omitted") — never
                # re-derive it from `op` here, that would duplicate/risk drifting from the resolution
                # logic that already ran.
                state.log.append_instance_moved(outcome.instance_id, outcome.instance.transform,
                                                actor="user", ts=_TS)
            else:
                state.log.append_instance_removed(outcome.instance_id, actor="user", ts=_TS)
                if state.active_instance_id == outcome.instance_id:  # it just got removed -> fall
                    # back to whatever's left (None if the file is now empty) — no root to fall back to
                    state.active_instance_id = next(iter(state.ledger().instances), None)
        return {
            "ok": outcome.changed,
            "status": outcome.status.value,
            "instance_id": outcome.instance_id,
            "instance": outcome.instance.model_dump(mode="json") if outcome.instance is not None else None,
            "previous_instance": (outcome.previous_instance.model_dump(mode="json")
                                  if outcome.previous_instance is not None else None),
            "message": outcome.message,
        }

    @router.post("/export/check")
    def export_check():
        # derived is resolved from the latest matching analysis verdict (stale -> unknown -> blocked);
        # discipline gates (thermal, …) are injected so a thermal-limited part also blocks honestly.
        return evaluate_export_gates(
            state.resolved_ledger(), extra_findings=all_discipline_findings
        ).model_dump(mode="json")

    def _requirements_payload() -> dict:
        # judge the stated goal against the LIVE grounded metrics — FS from the real verdict (UNKNOWN
        # if geometry changed since the last analysis), mass/time from deterministic geometry.
        metrics = state.metrics()
        results = state.matrix.evaluate(metrics)
        return {
            "goal_set": bool(state.matrix.requirements),
            "implied_fs_floor": state.strategic.floor_fs(state.matrix),  # the FS the goal demands
            "enforced_fs_floor": state.effective_fs_floor(),             # what the export gate enforces
            "implied_load_n": state.stated_load_n,  # the applied load the goal stated, if any
            "metrics": metrics,
            "satisfied": sum(1 for r in results if r.status.value == "SATISFIED"),
            "total": len(results),
            "requirements": [
                {"id": r.requirement.id, "text": r.requirement.text, "metric": r.requirement.metric,
                 "op": r.requirement.op, "target": r.requirement.target,
                 "method": r.requirement.method.value, "status": r.status.value, "value": r.value}
                for r in results
            ],
        }

    @router.post("/requirements")
    def set_requirements(req: GoalRequest):
        # fed from the chat: extract any stated TARGETS and fold them into the goal (never a safety value)
        state.note_message(req.goal)
        return _requirements_payload()

    @router.get("/requirements")
    def get_requirements():
        return _requirements_payload()

    @router.post("/analyze")
    async def analyze(material: str = "PLA", load_n: float | None = None):
        # generalized (2026-07-03): runs against whichever subsystem the ACTIVE instance is. Real FS
        # only comes back for `fea_eligible` parts (analyze_geometry itself gates this) — every other
        # part gets a well-formed Verdict with factor_of_safety=None, the honest "unknown".
        # load_n (2026-07-15): an explicit caller value always wins; otherwise resolve to whatever the
        # stated goal demands (state.effective_load_n), falling back to the historical 40 N default —
        # see FileState.effective_load_n's docstring for why this must not stay a bare hardcoded value.
        load_n = load_n if load_n is not None else state.effective_load_n(40.0)
        inst = state.active_instance()
        if inst is None:  # empty workspace — nothing to analyze yet
            return {"status": "error", "message": "no active part to analyze — add one first"}
        subsystem_name = inst.subsystem_type
        params = state.current_params()
        # the active instance's own cut_features MUST ride along with the analysis — otherwise this
        # solves the FS of the UN-CUT geometry while /mesh and /export/step show the cut part (see
        # packages/truth_plane/analysis.py::analyze_geometry's docstring). Dramatiq's queued path is
        # JSON-encoded, so dump to plain dicts for `.send()`; the inline path can hand the typed
        # models straight through (analyze_in_subprocess accepts either).
        cut_features = [f.model_dump(mode="json") for f in inst.cut_features]
        fp = fingerprint()
        gp = geometry_paths(get_subsystem_model(subsystem_name), inst.id)
        # material/load_n must match the CASE actually requested here — otherwise a verdict solved
        # for a different load (e.g. /optimize's 25 N sweep) could be served back as "grounded" for
        # this request (the exact fabricated-green-light failure Inversion #1 exists to prevent).
        cached = latest_verdict(state.ledger(), state.verdict_store.verdicts(state.project_id),
                                fingerprint=fp, geometry_params=gp, instance_id=inst.id,
                                material=material, load_n=load_n)
        if cached:
            return {"status": "done", "cached": True, "verdict": dataclasses.asdict(cached), "load_n": load_n}
        if os.environ.get("REDIS_URL"):  # durable queued path (worker + Postgres) — poll /analyze/status
            # NOTE: no jobs.configure() here — the actor body runs in the SEPARATE worker process,
            # which already configured its own store/status_store once at startup
            # (packages/truth_plane/worker.py); calling configure() in THIS (web) process has no
            # effect on it (2026-07-15 — removed dead code that suggested otherwise). Recording
            # "queued" here IS meaningful: it's the only signal a poller gets before the worker
            # actually picks the job up.
            from packages.truth_plane import jobs
            state.status_store.put_status(state.project_id, "queued")
            jobs.run_fs_analysis.send(state.project_id, params, material, load_n, subsystem_name, cut_features)
            # echo the RESOLVED load back — the poller must ask /analyze/status about this exact same
            # (material, load_n) case, not re-derive it (the goal could change mid-poll otherwise).
            return {"status": "queued", "load_n": load_n}
        # inline path: run the real FS (in a child process via the threadpool) — needs solvers
        try:
            verdict = await run_in_threadpool(analyze_in_subprocess, params, material, load_n, subsystem_name,
                                              cut_features=cut_features)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        state.verdict_store.put_verdict(state.project_id, verdict)
        return {"status": "done", "verdict": dataclasses.asdict(verdict), "load_n": load_n}

    @router.post("/optimize")
    async def optimize(load_n: float | None = None):
        # the sanctioned 3-variant sweep: find the lightest design that passes FS. Generalized
        # (2026-07-03) past bracket-only: discovers the ACTIVE subsystem's own thickness-like param
        # (packages/truth_plane/analysis.py::_thickness_param_name) instead of a hardcoded
        # skin_thickness_mm sweep. A subsystem with no such param (e.g. a cylindrical/rotational
        # part, or one that isn't fea_eligible) gets an honest "unsupported" instead of a wrong or
        # no-op sweep — the same "never fabricate" stance as analyze_geometry's own gating.
        # load_n (2026-07-15): same resolution as /analyze — an explicit caller value wins, else the
        # stated goal's load, else the historical 25 N default.
        from packages.truth_plane.analysis import _thickness_param_name
        from packages.subsystems import get_subsystem_model

        load_n = load_n if load_n is not None else state.effective_load_n(25.0)
        inst = state.active_instance()
        if inst is None:  # empty workspace — nothing to optimize yet
            return {"status": "unsupported", "message": "no active part to optimize — add one first"}
        sub_model = get_subsystem_model(inst.subsystem_type)
        thickness_name = _thickness_param_name(sub_model) if sub_model.fea_eligible else None
        if thickness_name is None:
            return {"status": "unsupported",
                    "message": f"optimize has no sweep target for {inst.subsystem_type!r} "
                               f"(needs a fea_eligible subsystem with a *_thickness_mm param)"}
        led = state.ledger()
        lo, hi = inst.params[thickness_name].bounds
        base_params = state.current_params()  # the rest of the geometry, held fixed across the sweep
        fs_floor = state.effective_fs_floor()  # optimize toward the STATED goal, not just the default
        # same rationale as /analyze: the sweep must solve the CUT geometry, and the resulting
        # best_verdict's signature must match what /analyze's cache check computes later (it now
        # folds cut_features in too — packages/ledger/derived_resolver.py::geometry_signature).
        cut_features = [f.model_dump(mode="json") for f in inst.cut_features]
        candidates = [c for c in (2.0, 3.0, 4.0, 5.0) if lo <= c <= hi]
        if os.environ.get("REDIS_URL"):  # durable queued path (worker) — poll /optimize/status
            # see /analyze's identical comment: no jobs.configure() here, it has no effect on the
            # separate worker process; state.status_store.put_status is the meaningful part.
            from packages.truth_plane import jobs
            state.status_store.put_status(state.project_id, "queued")
            jobs.run_optimization.send(state.project_id, candidates, base_params, "PLA", load_n, fs_floor,
                                       inst.subsystem_type, cut_features)
            return {"status": "queued", "load_n": load_n}
        try:  # inline (dev/tests): run the sweep in a child process
            result = await run_in_threadpool(optimize_in_subprocess, candidates, base_params, "PLA",
                                             load_n, fs_floor, 600.0, inst.subsystem_type, cut_features)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        best_value = result["best_value"]
        target_node = f"instances.{inst.id}.params.{thickness_name}"
        if best_value is not None:
            # target the ACTIVE instance specifically (not always "root" — a non-root instance can be
            # the one being optimized once the outliner has more than one instance in the tree).
            delta = ParameterDelta(target_node=target_node, requested_value=best_value)
            _, outcome = apply_delta(led, delta)
            if outcome.changed:
                state.log.append_mutation(delta, actor="optimizer", ts=_TS)
            state.verdict_store.put_verdict(state.project_id, result["best_verdict"])
        return {"status": "done", "variants": result["variants"], "best_value": best_value,
                "param_name": thickness_name, "target_node": target_node,
                "best_mass_g": result["best_mass_g"], "fs_floor": fs_floor, "load_n": load_n}

    @router.get("/optimize/status")
    def optimize_status():
        # job_status/job_message (2026-07-15) surface a FAILED queued job durably — before this, a
        # crashed worker job left `result` None forever, indistinguishable from "still running", so
        # a poller (or a human) had no way to tell "give it more time" from "this will never finish".
        job_status = state.status_store.get_status(state.project_id)
        return {"result": state.verdict_store.get_optimize(state.project_id),
                "job_status": job_status.status if job_status else None,
                "job_message": job_status.message if job_status else None}

    @router.get("/analyze/status")
    def analyze_status(material: str = "PLA", load_n: float | None = None):
        # material/load_n default to match POST /analyze's own resolution — a poller must ask about the
        # SAME case it queued, not just "any verdict for this geometry" (see /analyze's own comment).
        # Callers should pass back the exact `load_n` POST /analyze's response echoed, rather than rely
        # on this default recomputing the same value (the stated goal could change mid-poll otherwise).
        load_n = load_n if load_n is not None else state.effective_load_n(40.0)
        inst = state.active_instance()
        gp = geometry_paths(get_subsystem_model(inst.subsystem_type), inst.id) if inst is not None else None
        v = latest_verdict(state.ledger(), state.verdict_store.verdicts(state.project_id),
                           fingerprint=fingerprint(), geometry_params=gp,
                           instance_id=inst.id if inst is not None else None,
                           material=material, load_n=load_n)
        job_status = state.status_store.get_status(state.project_id)
        return {"current": dataclasses.asdict(v) if v else None,
                "job_status": job_status.status if job_status else None,
                "job_message": job_status.message if job_status else None}

    @router.post("/signoff")
    def signoff(reviewer: str = "engineer"):
        state.signoff(reviewer)
        return {"ok": True}

    @router.get("/export/step")
    def export_step():
        # Inversion #1's enforcement point: a missing/failing safety gate BLOCKS export, here — not
        # just in the advisory POST /export/check that a client can choose not to call. Same gate
        # evaluation export_check uses, so "checked eligible" and "will actually export" never diverge.
        gate = evaluate_export_gates(state.resolved_ledger(), extra_findings=all_discipline_findings)
        if not gate.eligible:
            return JSONResponse(
                status_code=409,
                content={"status": "error", "message": "export blocked by gates",
                         "reasons": gate.reasons, "unknowns": gate.unknowns},
            )
        # geometry is resolved from the WHOLE assembly once a project holds more than one instance
        # (packages/subsystems/assembly.py::render_assembly), else exactly the active instance's own
        # geometry — see _render_geometry.
        from packages.truth_plane.regen.export import export_part
        led = state.ledger()
        part = _render_geometry(led, state.active_instance_id)
        if part is None:
            return {"status": "error", "message": "no geometry to export"}
        name = "assembly" if len(led.instances) > 1 else get_subsystem(state.active_instance().subsystem_type).name
        fd, path = tempfile.mkstemp(suffix=".step")
        os.close(fd)
        export_part(part.solid, path)
        return FileResponse(path, media_type="application/step", filename=f"{name}.step",
                            background=BackgroundTask(os.remove, path))

    @router.get("/telemetry")
    def telemetry():
        # REST-fetchable telemetry (2026-07-04) — the WS `/ws` path already pushes a
        # `telemetry_delta` on every PARAMETER_CASCADE_UPDATE, but adding/removing a part via REST
        # (`/instances`, `/instance_ops`) never touches that socket, so Mass/CG/Print/Cost used to
        # sit on "—" until the user first touched a slider. This lets the frontend refresh them
        # right after any instance change too. `_telemetry` already handles an empty file (BOM-only,
        # zero structural mass) — safe to call unconditionally.
        return _telemetry(state.ledger(), state.active_instance_id).model_dump(mode="json")

    @router.post("/propose")
    def propose(req: ProposeRequest):
        # OpenRouter only — no mock. No key -> no LLM (the caller must say so, not fake a result).
        from packages.agents.provider_factory import get_provider
        provider = get_provider(req.api_key, req.model or None)
        if provider is None:
            return {"deltas": [], "clarification": None, "provider": "none", "no_llm": True}
        try:
            proposal = provider.propose_delta(
                system="", conversation=[{"role": "user", "content": req.intent}],
                ledger_json=state.ledger().model_dump_json(),
            )
        except Exception as e:  # bad key / model / network -> a message, not a 500
            return {"deltas": [], "clarification": f"LLM call failed: {e}", "provider": "openrouter", "no_llm": False}
        return {"deltas": [d.model_dump(mode="json") for d in proposal.deltas],
                "clarification": proposal.request_clarification,
                "provider": "openrouter", "no_llm": False}

    @router.post("/chat")
    def chat(req: ChatRequest):
        # Streams a conversational reply (prose) + an optional delta proposal. Mutates nothing —
        # the client applies any deltas via the rules-validated WS path.
        def gen():
            if not req.api_key:
                yield _sse({"type": "no_llm"})
                return
            from packages.agents.openrouter_provider import OpenRouterDeltaProvider
            provider = OpenRouterDeltaProvider(api_key=req.api_key, model=req.model or None)
            ledger_json = state.ledger().model_dump_json()
            for kind, payload in provider.stream_chat(messages=req.messages, ledger_json=ledger_json):
                if kind == "token":
                    yield _sse({"type": "token", "text": payload})
                elif kind == "proposal":
                    yield _sse({"type": "proposal",
                                "deltas": [d.model_dump(mode="json") for d in payload.deltas],
                                "feature_ops": [fo.model_dump(mode="json") for fo in payload.feature_ops],
                                "instance_ops": [io.model_dump(mode="json") for io in payload.instance_ops],
                                "clarification": payload.request_clarification,
                                "suggestions": payload.suggestions})
                elif kind == "error":
                    yield _sse({"type": "error", "message": payload})
                elif kind == "done":
                    yield _sse({"type": "done"})

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/mesh")
    def mesh():
        # the REAL build123d geometry, tessellated from the current ledger — the whole assembly once
        # a project holds more than one instance, else exactly the active instance (see
        # _render_geometry). Handles COMPOUND parts (multi-body designs like enclosure = box + lid,
        # or a multi-instance assembly) by iterating .solids() — a plain Solid iterates as one-item,
        # a Compound iterates as its children.
        led = state.ledger()
        part = _render_geometry(led, state.active_instance_id)
        if part is None:
            return {"positions": [], "indices": []}
        positions: list[float] = []
        indices: list[int] = []
        try:
            bodies = list(part.solid.solids())
        except AttributeError:
            bodies = [part.solid]
        if not bodies:  # some build123d versions return empty for a bare Solid
            bodies = [part.solid]
        for body in bodies:
            verts, tris = body.tessellate(0.2)
            base = len(positions) // 3
            positions.extend(c for v in verts for c in (v.X, v.Y, v.Z))
            indices.extend(int(i) + base for t in tris for i in t)
        return {"positions": positions, "indices": indices}

    @router.get("/mesh/features")
    def mesh_features():
        # rough click-to-select groundwork (prd4.md Phase 3's "context-aware floating HUD" —
        # precise version needs OCCT topological identity, specialist-gated; this reuses the
        # generator-baked TAGS every subsystem already produces instead). Pure/no build123d cost
        # beyond what /mesh itself already pays (same geometry_builder calls).
        from packages.subsystems.features import list_pickable_features
        return {"features": list_pickable_features(state.ledger())}

    app.include_router(router)

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        # Can't use the `_require_session` dependency here — a browser's native WebSocket API cannot
        # set custom headers, so the ONLY way a real browser client authenticates is by already
        # holding a session cookie minted by an earlier authenticated REST call (every page load does
        # at least one before opening this socket — packages/frontend/src/useCadSocket.ts relies on
        # exactly this, never the path below). A non-browser client (tests, scripts) CAN set an
        # Authorization header on the handshake to mint a session directly — but note that mint is
        # NOT reliably reusable across separate connections: this accept()'s Set-Cookie header is
        # only ever readable by a REAL browser's cookie jar, not by Starlette's WebSocketTestSession
        # or most raw WS client libraries (2026-07-15 audit finding) — a script relying on this path
        # for anything beyond a single connection's own lifetime should authenticate via REST first,
        # exactly like a browser does, and carry that cookie into the WS handshake instead.
        session_id = socket.cookies.get(SessionManager.COOKIE_NAME)
        existing = sessions.resolve(session_id)
        if existing is None and not _check_auth_token(socket.headers):
            await socket.close(code=1008)  # policy violation
            return
        try:
            sid, session, is_new = sessions.get_or_create(session_id)
        except SessionLimitReached:
            await socket.close(code=1013)  # try again later
            return
        accept_headers = []
        if is_new:
            cookie = f"{SessionManager.COOKIE_NAME}={sid}; HttpOnly; SameSite=lax; Path=/"
            accept_headers.append((b"set-cookie", cookie.encode()))
        await socket.accept(headers=accept_headers or None)
        session_ctx = _current_session.set(session)
        try:
            while True:
                raw = None
                try:
                    raw = await socket.receive_json()
                    req = ParamMutationRequest.model_validate(raw)
                except WebSocketDisconnect:
                    raise
                except Exception as e:
                    # a malformed frame (invalid JSON, missing/extra/wrong-type field — the protocol
                    # is extra="forbid") must NACK, not tear down the whole socket: previously an
                    # uncaught ValidationError/JSONDecodeError propagated out of this handler and
                    # killed the connection on the client's very next bad message, with no signal
                    # sent back at all and every other in-flight mutation on this socket lost with it.
                    bad_target = raw.get("target_node") if isinstance(raw, dict) else None
                    await socket.send_json(MutationRejected(
                        target_node=str(bad_target) if bad_target is not None else "",
                        status="REJECTED", reason=f"malformed frame: {e}",
                    ).model_dump(mode="json"))
                    continue
                await socket.send_json(state.mutate(req).model_dump(mode="json"))
        except WebSocketDisconnect:
            return
        finally:
            _current_session.reset(session_ctx)

    # serve the built SPA (compose deployment) from the same origin as the API — added LAST so API
    # routes win. In dev the frontend runs under Vite instead; this dir simply won't exist. Public —
    # a browser's top-level navigation to this origin can't carry a Bearer token, so the SPA shell
    # itself is always servable; every actual API call it then makes still goes through `router`.
    dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
    if os.path.isdir(dist):
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app
