"""Geometric self-check (2026-07-19) — deterministic structural validation of the built assembly, no
vision model in the loop. The honest backbone of the self-verifying build loop: every failure the user
actually hit this session (wing floating in empty space, a part engulfed invisibly inside another, a
degenerate build) is catchable here from the real placed solids, reliably, with zero model dependency.

Scope of THIS layer: INTENT-FREE STRUCTURAL checks — is the assembly well-FORMED, regardless of what it
was supposed to be. It cannot judge intent ("is this a flying wing? is the span 1000mm?") — that needs
the design scope/goal (a later harness piece) or the qualitative vision check
(packages/agents/vision_validator.py). Kept deliberately separate so the reliable part never depends on
a model's eyesight.

All checks are bounding-box / volume heuristics over each instance's WORLD-placed solid (same placement
`assembly.render_assembly` / the blueprint use), so this is cheap and needs no boolean ops. Heuristic by
design — a bbox proxy for "parts are joined" has occasional false edges (two L-shapes whose boxes
overlap without the solids touching); the report is advisory input for the copilot/user to act on, not a
hard gate. build123d is imported lazily so importing this module never drags in the kernel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict

from packages.subsystems import get_subsystem
from packages.subsystems.assembly import instance_world_offsets

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger

_logger = logging.getLogger(__name__)

# A part whose bbox is separated from every other part by more than this (per-axis) is "floating".
# 1mm of slack so a seam that just touches still counts as connected.
_GAP_TOL_MM = 1.0
# Degenerate-volume floor (mm^3) — below this a "solid" is effectively nothing.
_MIN_VOLUME_MM3 = 1e-3
# A part is "engulfed" if its bbox sits fully inside another's (this margin of slack) AND is much
# smaller — i.e. it contributes no visible/structural extent of its own.
_EMBED_MARGIN_MM = 0.5
_EMBED_VOLUME_RATIO = 0.5  # engulfed part's volume < this * the container's


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str                 # "degeneracy" | "connectivity" | "embedding"
    severity: str              # "error" | "warning" | "info"
    message: str
    instances: list[str]       # the instance ids involved


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool                   # no error-severity issues (warnings don't flip this)
    issues: list[ValidationIssue]
    summary: str


BBox = tuple[tuple[float, float, float], tuple[float, float, float]]  # (min xyz, max xyz)


def _placed(ledger: "MasterParametricLedger") -> dict[str, dict]:
    """Each instance -> {bbox, volume, valid, subsystem} of its WORLD-placed solid, or {error,...}."""
    import build123d as bd

    offsets = instance_world_offsets(ledger)
    out: dict[str, dict] = {}
    for iid, inst in ledger.instances.items():
        try:
            builder = get_subsystem(inst.subsystem_type).geometry_builder
            if builder is None:
                continue
            part = builder(ledger, iid)
            if part is None:
                continue
            solid = part.solid
            rx = ry = rz = 0.0
            if inst.transform is not None:
                rx, ry, rz = inst.transform.rx_deg, inst.transform.ry_deg, inst.transform.rz_deg
            if rx or ry or rz:
                solid = bd.Rotation(rx, ry, rz) * solid
            ox, oy, oz = offsets.get(iid, (0.0, 0.0, 0.0))
            solid = bd.Pos(ox, oy, oz) * solid
            bb = solid.bounding_box()
            out[iid] = {
                "bbox": ((bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z)),
                "volume": float(solid.volume),
                "valid": bool(solid.is_valid),
                "subsystem": inst.subsystem_type,
            }
        except Exception as e:  # a broken part is a finding, not a crash
            _logger.exception("validate: instance %s (%s) failed to build", iid, inst.subsystem_type)
            out[iid] = {"error": str(e), "subsystem": inst.subsystem_type}
    return out


def _axis_gap(b1: BBox, b2: BBox) -> float:
    """Largest per-axis separation between two AABBs (0 if they overlap/touch on every axis). A
    positive value means the boxes are apart — a lower bound on the true surface distance, enough to
    report 'this part floats ~N mm from anything else'."""
    (a0, a1), (c0, c1) = b1, b2
    gap = 0.0
    for ax in range(3):
        if a1[ax] < c0[ax]:
            gap = max(gap, c0[ax] - a1[ax])
        elif c1[ax] < a0[ax]:
            gap = max(gap, a0[ax] - c1[ax])
    return gap


def _touching(b1: BBox, b2: BBox, tol: float = _GAP_TOL_MM) -> bool:
    return _axis_gap(b1, b2) <= tol


def _inside(inner: BBox, outer: BBox, margin: float = _EMBED_MARGIN_MM) -> bool:
    (i0, i1), (o0, o1) = inner, outer
    return all(o0[ax] - margin <= i0[ax] and i1[ax] <= o1[ax] + margin for ax in range(3))


def validate_geometry(ledger: "MasterParametricLedger") -> ValidationReport:
    """Structural self-check of the whole assembly. Returns a `ValidationReport` (`ok` is True iff no
    error-severity issue). Empty/single-part files trivially pass connectivity."""
    placed = _placed(ledger)
    issues: list[ValidationIssue] = []

    # --- degeneracy: a part that failed to build, is invalid, or has ~zero volume ---
    healthy: dict[str, dict] = {}
    for iid, info in placed.items():
        if "error" in info:
            issues.append(ValidationIssue(check="degeneracy", severity="error",
                message=f"{iid} ({info['subsystem']}) failed to build: {info['error']}", instances=[iid]))
            continue
        if not info["valid"]:
            issues.append(ValidationIssue(check="degeneracy", severity="error",
                message=f"{iid} ({info['subsystem']}) built an INVALID solid", instances=[iid]))
            continue
        if info["volume"] <= _MIN_VOLUME_MM3:
            issues.append(ValidationIssue(check="degeneracy", severity="error",
                message=f"{iid} ({info['subsystem']}) has ~zero volume ({info['volume']:.3g} mm^3) — degenerate", instances=[iid]))
            continue
        healthy[iid] = info

    ids = list(healthy)

    # --- connectivity: parts should form ONE joined body (a floating part is almost always a
    # placement mistake — the wing-in-empty-space failure). Warning, not error: a deliberate kit of
    # separate parts is legitimate; the scope layer can later escalate this for a design meant to be
    # one connected vehicle. Reports the gap so the fix is actionable. ---
    if len(ids) >= 2:
        # union-find over bbox adjacency
        parent = {i: i for i in ids}
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                if _touching(healthy[ids[a]]["bbox"], healthy[ids[b]]["bbox"]):
                    parent[find(ids[a])] = find(ids[b])
        comps: dict[str, list[str]] = {}
        for i in ids:
            comps.setdefault(find(i), []).append(i)
        if len(comps) > 1:
            main = max(comps.values(), key=len)
            for comp in comps.values():
                if comp is main:
                    continue
                for iid in comp:
                    nearest_gap = min(_axis_gap(healthy[iid]["bbox"], healthy[o]["bbox"])
                                      for o in ids if o != iid)
                    issues.append(ValidationIssue(check="connectivity", severity="warning",
                        message=(f"{iid} ({healthy[iid]['subsystem']}) is disconnected — it floats "
                                 f"~{nearest_gap:.0f} mm from the nearest other part, not joined to the "
                                 f"assembly. If it should attach, move it so it touches/overlaps its host."),
                        instances=[iid]))

    # --- embedding: a part fully inside another and much smaller. This is AMBIGUOUS by nature — it
    # could be the wing-buried-in-body failure OR a deliberately-internal component (a battery, a
    # spar, a payload inside a hollow body — entirely legitimate). We can't tell intent from geometry,
    # so this is INFO severity, NOT a warning: it never flips `ok` and never drives an auto-correction
    # (a false "move the battery outside" would be worse than silence). It's a heads-up only. ---
    for iid in ids:
        for oid in ids:
            if iid == oid:
                continue
            if (_inside(healthy[iid]["bbox"], healthy[oid]["bbox"])
                    and healthy[iid]["volume"] < _EMBED_VOLUME_RATIO * healthy[oid]["volume"]):
                issues.append(ValidationIssue(check="embedding", severity="info",
                    message=(f"{iid} ({healthy[iid]['subsystem']}) sits entirely inside {oid} "
                             f"({healthy[oid]['subsystem']}). If it's meant to be an internal component "
                             f"(battery, spar, payload) this is fine; if it was meant to be visible/"
                             f"external, enlarge it or move it so part of it projects outside {oid}."),
                    instances=[iid, oid]))
                break

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    ok = not errors
    if not placed:
        summary = "empty file — nothing to validate yet"
    elif not issues:
        summary = f"{len(ids)} part(s), all structurally sound"
    else:
        summary = (f"{len(ids)} part(s): {len(errors)} error(s), {len(warnings)} warning(s) — "
                   + "; ".join(i.message for i in issues[:4]) + ("…" if len(issues) > 4 else ""))
    return ValidationReport(ok=ok, issues=issues, summary=summary)
