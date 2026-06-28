"""FastAPI app tying the backbone together: the two-plane WS + export REST.

Tier 0 only (in-process, closed-form): a slider mutation is rules-validated, committed to the event
log if it changes state, and answered with a cascade + analytic telemetry — or a NACK. The kernel and
solver tiers live behind the Truth Plane and are out of this hot path by design.
"""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict

from packages.ledger.apply import apply_delta
from packages.ledger.bom import BOM, Component, ComponentKind, material
from packages.ledger.deltas import ParameterDelta
from packages.ledger.events import EventLog
from packages.ledger.gates import evaluate_export_gates
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
    api_key: str | None = None   # user-supplied OpenRouter key (else the offline mock is used)
    model: str | None = None


class SessionState:
    def __init__(self) -> None:
        self.log = EventLog()
        self.log.append_genesis(make_demo_ledger(), actor="system", ts=_TS)

    def ledger(self) -> MasterParametricLedger:
        return self.log.fold()

    def mutate(self, req: ParamMutationRequest):
        led = self.ledger()
        delta = ParameterDelta(target_node=req.target_node, requested_value=req.requested_value,
                               set_lock=LockState(req.set_lock) if req.set_lock else None)
        new, outcome = apply_delta(led, delta)
        if outcome.changed:
            self.log.append_mutation(delta, actor="user", ts=_TS)
            return CascadeUpdate(
                mutations_applied=[MutationApplied(node=outcome.target, value=outcome.new_value,
                                                   status=outcome.status.value)],
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
        return evaluate_export_gates(state.ledger()).model_dump(mode="json")

    @app.post("/propose")
    def propose(req: ProposeRequest):
        # OpenRouter (user key) if provided, else the offline mock — the LLM only proposes deltas.
        if req.api_key:
            from packages.agents.openrouter_provider import OpenRouterDeltaProvider
            provider = OpenRouterDeltaProvider(api_key=req.api_key, model=req.model or None)
        else:
            from packages.agents.mock_provider import MockProvider
            provider = MockProvider()
        proposal = provider.propose_delta(
            system="", conversation=[{"role": "user", "content": req.intent}],
            ledger_json=state.ledger().model_dump_json(),
        )
        return {"deltas": [d.model_dump(mode="json") for d in proposal.deltas],
                "clarification": proposal.request_clarification,
                "provider": "openrouter" if req.api_key else "mock"}

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

    return app
