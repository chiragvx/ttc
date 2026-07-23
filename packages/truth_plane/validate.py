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

from packages.subsystems import get_subsystem, get_subsystem_model
from packages.subsystems.assembly import instance_world_offsets
from packages.subsystems.placement import connection_issues, world_frame_for_interface

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
# A true 3D intersection deeper than this (on EVERY axis) is "interference", not a flush touching
# seam — see _overlap_mm/_interferes below.
_INTERFERE_TOL_MM = 0.5


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str                 # "degeneracy" | "connections" | "connectivity" | "embedding" | "interference" | "keepout"
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


def _overlap_mm(b1: BBox, b2: BBox) -> float:
    """The MINIMUM per-axis overlap depth between two AABBs — positive ONLY when they truly
    intersect in 3D on every axis at once, unlike `_axis_gap` (which reports 0 for both "just
    touching" and "deeply overlapping", since it only cares about separation, not penetration).
    Two boxes that merely touch/abut on one axis while nesting on the others (e.g. a bracket's
    mount face flush against a wall) have zero-or-negative overlap on that one axis, so the min
    across all 3 stays <= 0 — correctly NOT interference."""
    (a0, a1), (c0, c1) = b1, b2
    return min(min(a1[ax], c1[ax]) - max(a0[ax], c0[ax]) for ax in range(3))


def _interferes(b1: BBox, b2: BBox, tol: float = _INTERFERE_TOL_MM) -> bool:
    return _overlap_mm(b1, b2) > tol


def _point_to_bbox_mm(point: tuple[float, float, float], bbox: BBox) -> float:
    """Shortest distance from a point to an AABB (0 if the point is inside/on it)."""
    (o0, o1) = bbox
    d = [max(o0[ax] - point[ax], 0.0, point[ax] - o1[ax]) for ax in range(3)]
    return (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5


def _connected_partner(ledger: "MasterParametricLedger", instance_id: str, interface: str) -> Optional[str]:
    """The OTHER instance a specific (instance_id, interface) is declared connected to, or None."""
    for c in ledger.connections:
        if c.a.instance_id == instance_id and c.a.interface == interface:
            return c.b.instance_id
        if c.b.instance_id == instance_id and c.b.interface == interface:
            return c.a.instance_id
    return None


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

    # --- connections: dangling refs, or a mate that needs a rotation the v1 solver won't auto-place
    # (packages/subsystems/placement.py). A declared connection that can't resolve is a real error —
    # the parts won't be placed as intended. ---
    for msg in connection_issues(ledger):
        issues.append(ValidationIssue(check="connections", severity="warning", message=msg, instances=[]))

    # --- connectivity: parts should form ONE joined body (a floating part is almost always a
    # placement mistake — the wing-in-empty-space failure). Warning, not error: a deliberate kit of
    # separate parts is legitimate; the scope layer can later escalate this for a design meant to be
    # one connected vehicle. Reports the gap so the fix is actionable.
    # 2026-07-19 (Phase 1): a declared Connection now counts as "joined" — so a part legitimately mated
    # by a connection is NEVER falsely flagged as floating even if its bbox happens not to overlap
    # (thin parts, a small gap). Bbox adjacency still catches implicit/undeclared touching. ---
    if len(ids) >= 2:
        parent = {i: i for i in ids}
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        def union(x, y):
            if x in parent and y in parent:
                parent[find(x)] = find(y)
        # EXACT edges first: every valid connection joins its two endpoints
        for c in ledger.connections:
            union(c.a.instance_id, c.b.instance_id)
        # then implicit bbox adjacency
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                if _touching(healthy[ids[a]]["bbox"], healthy[ids[b]]["bbox"]):
                    union(ids[a], ids[b])
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

    # --- interference: two COMPARABLY-SIZED parts truly interpenetrating (positive overlap on
    # every axis, not just touching/abutting) with NOTHING declaring it intentional. Distinct from
    # `embedding` above (which is specifically about a much-SMALLER part fully engulfed by a much
    # bigger one — ambiguous, often a legitimate internal component) and from `connectivity`'s
    # bbox-touching (which treats overlap as a POSITIVE "joined" signal). Two comparably-sized,
    # unrelated parts truly overlapping is not ambiguous the same way — it's the "two brackets
    # stacked exactly on top of each other" failure (2026-07-22, live-observed + reproduced from a
    # botched self-correction that fell back to auto-layout, which is blind to where a
    # connection-mated part already sits): the embedding ratio didn't fire (equal volumes, not
    # < 0.5x) and bbox-touching filed it as "connected." Warning, not error — same philosophy as
    # `connections`/`connectivity` above (a bbox heuristic, advisory, never blocks export) — but
    # confident enough to drive the self-correct loop, unlike `embedding`.
    #
    # Gated on comparable size (same 0.5x ratio as embedding) so this does NOT fire on the
    # legitimate, EXPECTED mid-build state where `assembly.py`'s 2026-07-20 two-lane auto-layout
    # cursor deliberately clusters an ordinary system part near/inside a big airframe body's own
    # footprint before it's ever connected — that stays embedding's territory, not this one.
    # Exempted by ANY declared Connection between the exact pair (regardless of its advisory
    # `kind` — a declared connection already means "this touching/overlap is intentional"). ---
    connected_pairs = {frozenset((c.a.instance_id, c.b.instance_id)) for c in ledger.connections}
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            iid, oid = ids[a], ids[b]
            if frozenset((iid, oid)) in connected_pairs:
                continue
            bi, bo = healthy[iid], healthy[oid]
            smaller, larger = min(bi["volume"], bo["volume"]), max(bi["volume"], bo["volume"])
            if larger > 0 and smaller < _EMBED_VOLUME_RATIO * larger:
                continue  # comparable-size gate — a much-smaller part is embedding's territory
            if _interferes(bi["bbox"], bo["bbox"]):
                issues.append(ValidationIssue(check="interference", severity="warning",
                    message=(f"{iid} ({bi['subsystem']}) and {oid} ({bo['subsystem']}) physically "
                             f"overlap with no declared connection between them — two comparably-"
                             f"sized parts occupying the same space is almost always a placement "
                             f"mistake, not an intentional design. If this is intentional, add a "
                             f"connection between them; otherwise reposition one of them."),
                    instances=[iid, oid]))

    # --- keepout: an interface with a declared `keepout_mm` (InterfaceSpec, packages/subsystems/
    # base.py) needs that much clearance around its WORLD origin from every OTHER instance's
    # geometry, excluding whichever instance (if any) is legitimately connected to that exact
    # interface. Mechanism only today — no subsystem sets keepout_mm > 0 yet (deciding which parts
    # need how much clearance, e.g. a camera's line-of-sight cone, is a domain judgment deliberately
    # deferred); this check exists so that judgment has somewhere real to plug into once made. ---
    for iid, inst in ledger.instances.items():
        if iid not in healthy:
            continue
        try:
            model = get_subsystem_model(inst.subsystem_type)
        except KeyError:
            continue
        for spec in model.interfaces:
            if spec.keepout_mm <= 0:
                continue
            wf = world_frame_for_interface(ledger, iid, spec.name)
            if wf is None:
                continue
            partner = _connected_partner(ledger, iid, spec.name)
            for oid in ids:
                if oid == iid or oid == partner:
                    continue
                dist = _point_to_bbox_mm(wf.origin, healthy[oid]["bbox"])
                if dist < spec.keepout_mm:
                    issues.append(ValidationIssue(check="keepout", severity="warning",
                        message=(f"{iid} ({inst.subsystem_type})'s '{spec.name}' interface needs "
                                 f"{spec.keepout_mm:.0f} mm clear, but {oid} "
                                 f"({healthy[oid]['subsystem']}) comes within {dist:.1f} mm."),
                        instances=[iid, oid]))

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
