"""Fit resolver (2026-07-27) — the arithmetic behind `FitBinding` (packages/ledger/schema.py): derive
a CONNECTOR subsystem's own fitted-dimension params from a HOST subsystem's declared cross-section.
Pure arithmetic; NO OCCT/LLM/solver — mirrors packages/couplings/resolve.py's own framing exactly, one
layer earlier (geometry instead of a safety scalar).

This is the honest core: a fit whose host/connector don't declare compatible cross-sections, or whose
host has vanished, yields `ok=False` with a `reason` — never a fabricated dimension. A rect fit onto a
non-square host is refused for a different, structural reason: this codebase's placement solver
(packages/subsystems/placement.py) never auto-solves rotation, so an unverified-orientation bore is not
"close enough" — it either fits or it's wrong, and there's no way to tell which without rotation-solving
this repo doesn't have."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger

_SQUARE_TOL_MM = 1e-6


@dataclass(frozen=True)
class FitComputeResult:
    """The outcome of computing ONE fit. `ok=False` == "unknown" (with `reason`) — must block, never
    be treated as a pass. `values` is `{connector_param: computed_value}`; `dim_map` is
    `{host_dim_role: connector_param}`, recorded onto the FitBinding for later drift-checking."""

    ok: bool
    kind: Optional[str] = None
    values: dict[str, float] = field(default_factory=dict)
    dim_map: dict[str, str] = field(default_factory=dict)
    reason: Optional[str] = None


def compute_fit(
    ledger: "MasterParametricLedger", connector_id: str, host_id: str, clearance_mm: float,
) -> FitComputeResult:
    """Derive `connector_id`'s fitted dimensions from `host_id`'s current cross-section. Read-only —
    never mutates the ledger or writes anything; the caller (packages/ledger/apply.py::apply_fit_op)
    is what actually applies the result, through the ordinary ParameterDelta path."""
    from packages.subsystems import get_subsystem_model
    from packages.subsystems.base import resolve_namespace

    connector_inst = ledger.instances.get(connector_id)
    if connector_inst is None:
        return FitComputeResult(ok=False, reason=f"connector instance {connector_id!r} does not exist")
    host_inst = ledger.instances.get(host_id)
    if host_inst is None:
        return FitComputeResult(ok=False, reason=f"host instance {host_id!r} does not exist")

    try:
        connector_model = get_subsystem_model(connector_inst.subsystem_type)
    except KeyError:
        return FitComputeResult(ok=False, reason=f"unknown subsystem type {connector_inst.subsystem_type!r}")
    try:
        host_model = get_subsystem_model(host_inst.subsystem_type)
    except KeyError:
        return FitComputeResult(ok=False, reason=f"unknown subsystem type {host_inst.subsystem_type!r}")

    if connector_model.fit_socket is None:
        return FitComputeResult(ok=False, reason=(
            f"{connector_inst.subsystem_type!r} declares no fit_socket — it has no fittable socket "
            f"for anything to derive dimensions into"))
    if host_model.fit_profile is None:
        return FitComputeResult(ok=False, reason=(
            f"{host_inst.subsystem_type!r} declares no fit_profile — nothing can be fitted to it"))

    host_ns = resolve_namespace(host_model, ledger, host_id)
    profile = host_model.fit_profile(host_ns)
    socket = connector_model.fit_socket

    if socket.kind != profile.kind:
        return FitComputeResult(ok=False, reason=(
            f"cannot fit a {socket.kind!r} socket ({connector_id}) onto a {profile.kind!r} host "
            f"({host_id}) — kinds must match, never coerced"))

    # Rotation-safety gate (2026-07-27, grafted from the template-derived design during synthesis): a
    # rect fit is refused at THIS layer — compute time, called from op-apply time — unless the host's
    # cross-section is square. Never at render time only: a mis-fit rect connector must never even be
    # wired, let alone exported, since this codebase's placement solver always places a mated part
    # with zero rotation (never auto-solved) and an unverified-orientation bore is not fitted
    # geometry, it's a coin flip that happens to render.
    if profile.kind == "rect":
        w = profile.dims.get("width_mm")
        h = profile.dims.get("height_mm")
        if w is None or h is None or abs(w - h) > _SQUARE_TOL_MM:
            return FitComputeResult(ok=False, reason=(
                f"{host_id}'s cross-section is {w}x{h}mm, not square — a rect fit is refused unless "
                f"width_mm == height_mm, because this system never auto-solves rotation (the mate "
                f"solver always places a connected part with zero rotation) and a fit onto a "
                f"non-square section with unverified orientation is not a real fit"))

    values: dict[str, float] = {}
    dim_map: dict[str, str] = {}
    connector_param_names = {p.name for p in connector_model.params}
    for dim_role, connector_param in socket.dim_params.items():
        if dim_role not in profile.dims:
            return FitComputeResult(ok=False, reason=(
                f"host {host_id!r}'s {profile.kind!r} profile has no {dim_role!r} dimension "
                f"(has: {sorted(profile.dims)})"))
        if connector_param not in connector_param_names:
            return FitComputeResult(ok=False, reason=(
                f"connector {connector_id!r}'s fit_socket names {connector_param!r}, which isn't one "
                f"of its own declared params (has: {sorted(connector_param_names)})"))
        values[connector_param] = profile.dims[dim_role] + clearance_mm
        dim_map[dim_role] = connector_param

    return FitComputeResult(ok=True, kind=profile.kind, values=values, dim_map=dim_map)


def fit_gate_findings(
    ledger: "MasterParametricLedger", instance_id: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    """`(reasons, unknowns)` for the export gate — mirrors `packages/couplings/resolve.py::
    coupling_gate_findings` exactly. A binding whose host/connector can no longer be resolved into a
    real fit (deleted, retyped, cross-section vanished) makes the connector's fitted geometry unknown
    — that must block export, exactly like an unresolved coupling does. DRIFT (host present, resolves
    fine, but the connector's CURRENTLY-STORED dimensions no longer match what a fresh compute_fit
    would produce — the host was resized after this fit was wired) is deliberately NOT checked here;
    that's `fit_drift_findings` below, surfaced as an advisory self-check warning instead, not an
    export block — a stale-but-still-physically-real dimension is a "please resync" nudge, not the
    same category as a fit that was never grounded at all.

    `instance_id` (default None -> every binding) restricts to bindings targeting that connector,
    mirroring every other gate-finding function's own instance-scoping (foundations-audit H3 precedent)."""
    reasons: list[str] = []
    unknowns: list[str] = []
    for binding in ledger.fit_bindings:
        if instance_id is not None and binding.connector_instance != instance_id:
            continue
        result = compute_fit(ledger, binding.connector_instance, binding.host_instance, binding.clearance_mm)
        if not result.ok:
            unknowns.append(f"fit:{binding.id}")
            reasons.append(
                f"fit {binding.id} ({binding.connector_instance} <- {binding.host_instance}): {result.reason}")
    return reasons, unknowns


def fit_drift_findings(ledger: "MasterParametricLedger") -> list[str]:
    """Every live FitBinding whose connector's CURRENTLY-STORED dimensions no longer match what a
    fresh `compute_fit` would produce today — the host resized (or the connector's own params were
    hand-edited) since this fit was wired. Advisory: a real, actionable finding (the self-check loop
    should propose `resync_fit`), never a fabricated pass, but not export-blocking on its own — see
    `fit_gate_findings`'s own docstring for why dangling and drift are deliberately different severities."""
    findings: list[str] = []
    for binding in ledger.fit_bindings:
        result = compute_fit(ledger, binding.connector_instance, binding.host_instance, binding.clearance_mm)
        if not result.ok:
            continue  # dangling/unresolvable is fit_gate_findings' job, not this one's
        connector_inst = ledger.instances.get(binding.connector_instance)
        if connector_inst is None:
            continue
        for connector_param, expected in result.values.items():
            pd = connector_inst.params.get(connector_param)
            current = pd.value if pd is not None else None
            if current is None or abs(current - expected) > 1e-6:
                findings.append(
                    f"fit {binding.id}: {binding.connector_instance}.{connector_param} is "
                    f"{current if current is not None else 'missing'}, but {binding.host_instance} "
                    f"now implies {expected:.3f} — the host's dimensions changed since this fit was "
                    f"wired; run resync_fit on {binding.id} to update it")
                break  # one finding per binding is enough signal; don't spam per-dimension
    return findings
