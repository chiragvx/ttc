"""FastAPI app tying the backbone together: the two-plane WS + export REST.

Tier 0 only (in-process, closed-form): a slider mutation is rules-validated, committed to the event
log if it changes state, and answered with a cascade + analytic telemetry — or a NACK. The kernel and
solver tiers live behind the Truth Plane and are out of this hot path by design.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from starlette.background import BackgroundTask

from packages.ledger.apply import apply_delta
from packages.ledger.bom import BOM, Component, ComponentKind, material
from packages.ledger.deltas import ParameterDelta
from packages.ledger.events import EventLog
from packages.ledger.derived_resolver import latest_verdict, ledger_with_derived
from packages.ledger.fingerprint import fingerprint
from packages.ledger.gates import evaluate_export_gates
from packages.ledger.nodes import RIB, SKIN
from packages.truth_plane.analysis import analyze_geometry  # module-level so tests can monkeypatch it
from packages.truth_plane.verdict_store import InMemoryVerdictStore
from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import (
    Domains,
    GlobalConstraints,
    ManufacturingDomain,
    MasterParametricLedger,
    ProjectMetadata,
    StructureDomain,
)
from packages.transport.protocol import (
    CascadeUpdate,
    MutationApplied,
    MutationRejected,
    ParamMutationRequest,
    TelemetryDelta,
)

_PLATE_AREA_MM2 = 60.0 * 40.0  # demo: structural mass scales with skin thickness over this area
_PROFILE = "PLA"
_TS = "2026-06-28T00:00:00Z"


def _pd(value, lo, hi, lock=LockState.DYNAMIC):
    return ParameterDef(value=value, unit="mm", bounds=(lo, hi), lock_state=lock)


def make_demo_ledger() -> MasterParametricLedger:
    return MasterParametricLedger(
        project_metadata=ProjectMetadata(project_id="demo", version_commit="v0", branch="main"),
        global_constraints=GlobalConstraints(factor_of_safety_floor=1.5),
        domains=Domains(
            structure=StructureDomain(
                material_profile=_PROFILE,
                skin_thickness_mm=_pd(2.0, 1.0, 5.0),
                internal_rib_spacing_mm=_pd(20.0, 10.0, 50.0),
            ),
            manufacturing=ManufacturingDomain(
                build_orientation_deg=_pd(0.0, 0.0, 90.0),
                slip_fit_clearance_mm=_pd(0.2, 0.0, 1.0),
            ),
        ),
    )


_DEMO_BOM = BOM([
    Component("cellA", 70.0, (0.0, 0.0, 0.0), ComponentKind.POWER),
    Component("cellB", 70.0, (100.0, 0.0, 0.0), ComponentKind.POWER),
    Component("payload", 10.0, (200.0, 0.0, 0.0), ComponentKind.PAYLOAD),
])


def _telemetry(ledger: MasterParametricLedger) -> TelemetryDelta:
    skin = ledger.domains.structure.skin_thickness_mm.value
    vol = _PLATE_AREA_MM2 * skin
    structural_g = material(ledger.domains.structure.material_profile).density_g_per_mm3 * vol
    total = _DEMO_BOM.total_mass_g() + structural_g
    return TelemetryDelta(
        total_mass_g=round(total, 3),
        cg_mm=tuple(round(v, 3) for v in _DEMO_BOM.cg_mm()),
        estimated_print_time_s=round(vol / 5.0, 1),  # analytic estimate (labeled)
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


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _make_verdict_store():
    if os.environ.get("DATABASE_URL"):
        from packages.ledger.event_store_pg import PgVerdictStore
        return PgVerdictStore.from_env()
    return InMemoryVerdictStore()


def _make_event_log():
    if os.environ.get("DATABASE_URL"):
        from packages.ledger.event_store_pg import PgEventStore
        return PgEventStore.from_env()
    return EventLog()


class SessionState:
    def __init__(self) -> None:
        self.project_id = "demo"
        self.log = _make_event_log()
        if not self.log.events():  # fresh project -> seed genesis; else reuse the durable history
            self.log.append_genesis(make_demo_ledger(), actor="system", ts=_TS)
        self.verdict_store = _make_verdict_store()

    def ledger(self) -> MasterParametricLedger:
        return self.log.fold()

    def current_params(self) -> dict[str, float]:
        led = self.ledger()
        return {SKIN: led.domains.structure.skin_thickness_mm.value,
                RIB: led.domains.structure.internal_rib_spacing_mm.value}

    def resolved_ledger(self) -> MasterParametricLedger:
        # the export gate sees `derived` resolved from the latest matching analysis verdict
        return ledger_with_derived(self.ledger(), self.verdict_store.verdicts(self.project_id),
                                   fingerprint=fingerprint())

    def signoff(self, reviewer: str) -> None:
        self.log.append_signoff(reviewer, ts=_TS)

    def mutate(self, req: ParamMutationRequest):
        led = self.ledger()
        delta = ParameterDelta(target_node=req.target_node, requested_value=req.requested_value,
                               set_lock=LockState(req.set_lock) if req.set_lock else None)
        new, outcome = apply_delta(led, delta)
        if outcome.changed:
            self.log.append_mutation(delta, actor="user", ts=_TS)
            return CascadeUpdate(
                mutations_applied=[MutationApplied(node=outcome.target, value=outcome.new_value,
                                                   old_value=outcome.old_value, status=outcome.status.value)],
                telemetry_delta=_telemetry(new),
            )
        return MutationRejected(target_node=outcome.target, status=outcome.status.value,
                                reason=outcome.message or outcome.status.value)


def create_app() -> FastAPI:
    app = FastAPI(title="Grounded Text-to-CAD (Tier 0)")
    state = SessionState()

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/ledger")
    def get_ledger():
        return state.ledger().model_dump(mode="json")

    @app.post("/export/check")
    def export_check():
        # derived is resolved from the latest matching analysis verdict (stale -> unknown -> blocked)
        return evaluate_export_gates(state.resolved_ledger()).model_dump(mode="json")

    @app.post("/analyze")
    async def analyze(material: str = "PLA", load_n: float = 40.0):
        params = state.current_params()
        fp = fingerprint()
        cached = latest_verdict(state.ledger(), state.verdict_store.verdicts(state.project_id), fingerprint=fp)
        if cached:
            return {"status": "done", "cached": True, "verdict": dataclasses.asdict(cached)}
        if os.environ.get("REDIS_URL"):  # durable queued path (worker + Postgres) — poll /analyze/status
            from packages.truth_plane import jobs
            jobs.configure(store=state.verdict_store, publish=None)
            jobs.run_fs_analysis.send(state.project_id, params, material, load_n)
            return {"status": "queued"}
        # inline path: run the real FS in a threadpool (needs solvers — Linux container)
        try:
            verdict = await run_in_threadpool(analyze_geometry, params, material, load_n)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        state.verdict_store.put_verdict(state.project_id, verdict)
        return {"status": "done", "verdict": dataclasses.asdict(verdict)}

    @app.get("/analyze/status")
    def analyze_status():
        v = latest_verdict(state.ledger(), state.verdict_store.verdicts(state.project_id), fingerprint=fingerprint())
        return {"current": dataclasses.asdict(v) if v else None}

    @app.post("/signoff")
    def signoff(reviewer: str = "engineer"):
        state.signoff(reviewer)
        return {"ok": True}

    @app.get("/export/step")
    def export_step():
        from packages.truth_plane.regen.export import export_part
        from packages.truth_plane.regen.templated import render_bracket
        skin = state.current_params()[SKIN]
        part = render_bracket(width_mm=60.0, depth_mm=40.0, thickness_mm=max(1.0, skin), hole_dia_mm=6.0, n_holes=4)
        fd, path = tempfile.mkstemp(suffix=".step")
        os.close(fd)
        export_part(part.solid, path)
        return FileResponse(path, media_type="application/step", filename="bracket.step",
                            background=BackgroundTask(os.remove, path))

    @app.post("/propose")
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

    @app.post("/chat")
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
                                "clarification": payload.request_clarification,
                                "suggestions": payload.suggestions})
                elif kind == "error":
                    yield _sse({"type": "error", "message": payload})
                elif kind == "done":
                    yield _sse({"type": "done"})

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/mesh")
    def mesh(skin: float = 2.0):
        # the REAL build123d bracket (plate thickness tracks skin), tessellated for the viewport
        from packages.truth_plane.regen.templated import render_bracket
        part = render_bracket(width_mm=60.0, depth_mm=40.0, thickness_mm=max(1.0, skin),
                              hole_dia_mm=6.0, n_holes=4)
        verts, tris = part.solid.tessellate(0.2)
        positions = [c for v in verts for c in (v.X, v.Y, v.Z)]
        indices = [int(i) for t in tris for i in t]
        return {"positions": positions, "indices": indices}

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        try:
            while True:
                raw = await socket.receive_json()
                req = ParamMutationRequest.model_validate(raw)
                await socket.send_json(state.mutate(req).model_dump(mode="json"))
        except WebSocketDisconnect:
            return

    # serve the built SPA (compose deployment) from the same origin as the API — added LAST so API
    # routes win. In dev the frontend runs under Vite instead; this dir simply won't exist.
    dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
    if os.path.isdir(dist):
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app
