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

from packages.subsystems import get_subsystem_model, resolve_namespace
from packages.subsystems.assembly import instance_world_offsets
from packages.subsystems.envelope import compute_envelope
from packages.subsystems.fit import fit_drift_findings
from packages.subsystems.geometry_query import BBox
from packages.subsystems.placement import connection_issues, world_frame_for_interface

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger, Region
    from packages.subsystems.base import Subsystem

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
# DFM (2026-08-04) — both figures cited to build-plan/research03aug/parametric/
# final_packaging_structural_design_research.md section 2 (Xometry + Protolabs, cross-corroborated
# commercial injection-molding DFM sources). A rib/boss thicker than its host wall sinks/warps on
# cooling (uneven wall thickness -> uneven shrinkage); a face with less than the minimum draft won't
# release cleanly from its tool. Assumption a human should confirm: these are injection-molding-
# sourced figures, reused here as a general thick-section/draft heuristic for FDM/CNC parts too — the
# research doc's own section 4 rib-placement row found the underlying "don't let a thick feature rise
# off a thin wall unsupported" principle independently in both a plastics-DFM guide and metal
# gearbox-housing NVH papers, i.e. not molding-only, even though the exact ratio is molding-sourced.
_DFM_RIB_RATIO_MAX = 0.6   # "Rib thickness <= 60% of nominal wall" (Xometry); "Boss wall thickness
                           # 40-60% of the wall it rises from" (Protolabs) — section 2.
_DFM_DRAFT_MIN_DEG = 0.5   # "minimum 0.5 deg on all vertical faces" (Protolabs) — section 2. Only the
                           # floor is checked — the research doc documents no universal UPPER bound
                           # (more draft is a legitimate design choice, e.g. 3 deg+ for shutoffs/
                           # texture), so an upper-bound flag would be fabricating a rule the citation
                           # doesn't support.


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str                 # "degeneracy" | "connections" | "connectivity" | "embedding" | "interference" | "keepout" | "fit" | "dfm" | "region" | "envelope_missing" | "envelope_drift"
    severity: str              # "error" | "warning" | "info"
    message: str
    instances: list[str]       # the instance ids involved


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool                   # no error-severity issues (warnings don't flip this)
    issues: list[ValidationIssue]
    summary: str


def _connection_resolves(ledger: "MasterParametricLedger", c) -> bool:
    """True iff both of `c`'s endpoints exist AND each names a real interface declared on its own
    subsystem — same validity bar `packages/subsystems/placement.py::_adjacency` already applies
    before a connection enters the mate-placement graph. A dangling connection (e.g. one whose target
    interface no longer exists because the subsystem's declared interfaces changed) must not silently
    exempt its own endpoints from the connectivity/interference checks that unfiltered iteration over
    `ledger.connections` used to allow (2026-07-27, verified live: two coincident enclosures joined
    only by a bogus connection passed both checks silently before this filter)."""
    if c.a.instance_id not in ledger.instances or c.b.instance_id not in ledger.instances:
        return False
    for ref in (c.a, c.b):
        inst = ledger.instances[ref.instance_id]
        try:
            model = get_subsystem_model(inst.subsystem_type)
        except KeyError:
            return False
        if not any(s.name == ref.interface for s in model.interfaces):
            return False
    return True


def _placed(ledger: "MasterParametricLedger") -> dict[str, dict]:
    """Each instance -> {bbox, volume, valid, subsystem} of its WORLD-placed solid, or {error,...}."""
    import build123d as bd

    from packages.subsystems.geometry_query import raw_build

    offsets = instance_world_offsets(ledger)
    out: dict[str, dict] = {}
    for iid, inst in ledger.instances.items():
        try:
            # geometry_query.raw_build (2026-08-05, gearbox-housing Phase 0) shares the get-builder/
            # build/defend-against-None step with assembly.py/blueprint.py. Deliberately NOT
            # geometry_query.placed_solid/world_bbox here: both SWALLOW a build that raises (log +
            # return None), which would make a genuinely broken part invisible to this function
            # instead of the reported `degeneracy` error the `except` below (unchanged) produces --
            # collapsing that into the same silent "nothing to build here" skip a subsystem with no
            # geometry_builder legitimately gets (e.g. an assembly-template master node) would hide a
            # real defect instead of reporting it. See raw_build's own docstring.
            solid = raw_build(ledger, iid)
            if solid is None:
                continue
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


def _dfm_wall_rib_params(model: "Subsystem") -> Optional[tuple[str, str]]:
    """(wall_thickness_param, rib_thickness_param) if `model` exposes BOTH the established nominal-
    wall convention (the exact name `wall_thickness_mm` — see `enclosure.py`) AND a rib-thickness
    param (an underscore TOKEN `rib`, not just a substring — excludes false positives like a
    hypothetical `distribution_thickness_mm`, and excludes `bracket.py`'s real
    `internal_rib_spacing_mm`, which is a pitch, not a thickness) — else None. No subsystem in the
    catalog exposes both today (2026-08-04); every call site must skip cleanly rather than guess, the
    same discipline every other check in this file already holds to. Driven purely by NAMING
    CONVENTION over params that already exist for other reasons — unlike `keepout_mm` (a dedicated
    opt-in field nothing was ever taught to set), this activates automatically the moment any
    subsystem happens to declare matching param names, with zero further plumbing."""
    names = {p.name for p in model.params}
    if "wall_thickness_mm" not in names:
        return None
    rib = next((n for n in sorted(names)
                if "rib" in n.split("_") and n.endswith("thickness_mm")), None)
    if rib is None:
        return None
    return "wall_thickness_mm", rib


def _dfm_draft_param(model: "Subsystem") -> Optional[str]:
    """A declared draft-angle param (any name ending `draft_deg`) if `model` exposes one, else None.
    Same naming-convention/never-guess discipline as `_dfm_wall_rib_params` above."""
    return next((p.name for p in model.params if p.name.endswith("draft_deg")), None)


def _region_world_bbox(ledger: "MasterParametricLedger", region: "Region") -> Optional[BBox]:
    """A Region's world-space AABB — its LOCAL box (`region.x/y/z_mm` center, `region.dx/dy/dz_mm`
    extents, in the HOST's own local frame per `Region`'s own docstring) transformed the SAME way
    `_placed` transforms that host's own solid: rotate around the host's local origin using the
    host's `Transform`, THEN translate by the host's resolved world offset. None if the host instance
    no longer exists (a dangling `host_instance`, e.g. after the host was deleted)."""
    import build123d as bd

    if region.host_instance not in ledger.instances:
        return None
    inst = ledger.instances[region.host_instance]
    box = bd.Pos(region.x_mm, region.y_mm, region.z_mm) \
          * bd.Box(region.dx_mm, region.dy_mm, region.dz_mm)
    rx = ry = rz = 0.0
    if inst.transform is not None:
        rx, ry, rz = inst.transform.rx_deg, inst.transform.ry_deg, inst.transform.rz_deg
    if rx or ry or rz:
        box = bd.Rotation(rx, ry, rz) * box
    ox, oy, oz = instance_world_offsets(ledger).get(region.host_instance, (0.0, 0.0, 0.0))
    box = bd.Pos(ox, oy, oz) * box
    bb = box.bounding_box()
    return ((bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z))


def envelope_missing_findings(
    ledger: "MasterParametricLedger", instance_id: Optional[str] = None,
) -> list[tuple[str, str]]:
    """`(housing_instance_id, message)` for every housing-family instance (a subsystem declaring
    `envelope_socket` — Phase 2, packages/subsystems/base.py::EnvelopeSocketSpec) whose `wraps` is
    EMPTY or names an instance id that no longer exists in the ledger (2026-08-06, gearbox-housing-
    generation initiative Phase 4). This is the user's own named failure mode made concrete: "a
    housing was added before the group it's supposed to wrap was even placed" — not just incomplete,
    UNGROUNDED, exactly the "missing safety/construction input blocks export" posture Inversion #1
    already establishes elsewhere (CLAUDE.md). Same severity class as `packages/subsystems/fit.py::
    fit_gate_findings`'s own dangling/unresolvable case — export-BLOCKING, never merely advisory.

    Deliberately NOT `_`-prefixed: `packages/transport/app.py::_envelope_gate_findings` imports this
    SAME function to feed the real export gate (`evaluate_export_gates`'s `extra_findings`), so the
    self-check UI (`validate_geometry` below, which turns this into an `envelope_missing`
    `ValidationIssue`) and the actual export block are always looking at the identical detection —
    never two independently-drifting implementations of "what counts as missing."

    DRIFT (every member resolves, but the housing's stored dims no longer match a fresh
    `compute_envelope`) is deliberately NOT checked here — that's `_envelope_drift_findings` below,
    advisory-only, mirroring `fit_gate_findings`/`fit_drift_findings`'s own dangling-vs-drift split.

    `instance_id` (default None -> every housing) scopes to ONE housing, mirroring every other
    gate-finding function in this codebase's own per-instance scoping (foundations-audit H3)."""
    out: list[tuple[str, str]] = []
    for iid, inst in ledger.instances.items():
        if instance_id is not None and iid != instance_id:
            continue
        try:
            model = get_subsystem_model(inst.subsystem_type)
        except KeyError:
            continue
        if model.envelope_socket is None:
            continue
        if not inst.wraps:
            out.append((iid, (
                f"{iid} ({inst.subsystem_type}) is a housing (declares envelope_socket) but its wraps "
                f"list is empty — nothing is wired for it to derive an envelope from. Run wrap_group "
                f"before proposing its shell/DFM features.")))
            continue
        missing = [m for m in inst.wraps if m not in ledger.instances]
        if missing:
            out.append((iid, (
                f"{iid} ({inst.subsystem_type}) wraps unknown instance id(s) {missing!r} — every "
                f"member of wraps must be a real instance still present in the ledger.")))
    return out


def _envelope_drift_findings(ledger: "MasterParametricLedger") -> list[str]:
    """Every housing-family instance whose `wraps` fully resolves (an `envelope_missing_findings`
    subject is skipped here — dangling is that function's territory, not drift's) but whose OWN
    CURRENTLY-STORED `envelope_socket`-mapped dims no longer match what a FRESH `compute_envelope` call
    would produce right now — the wrapped group moved/resized since the housing was last derived.
    Advisory only: a real, actionable finding (drives the self-check loop's `resync_envelope`
    suggestion), never a fabricated pass, but NOT export-blocking on its own — mirrors `packages/
    subsystems/fit.py::fit_drift_findings`'s own dangling-vs-drift severity split exactly, one layer
    out (a housing whose dims are merely stale is not "missing," it's just out of date).

    A housing whose `compute_envelope` call fails for a reason OTHER than dangling members (e.g. no
    wraps member produced buildable geometry) is silently skipped here — out of THIS check's scope;
    only the empty/dangling-`wraps` case is a defined finding in this phase (`envelope_missing_findings`
    above), matching that function's own explicitly narrow definition."""
    findings: list[str] = []
    for iid, inst in ledger.instances.items():
        try:
            model = get_subsystem_model(inst.subsystem_type)
        except KeyError:
            continue
        if model.envelope_socket is None or not inst.wraps:
            continue
        if any(m not in ledger.instances for m in inst.wraps):
            continue  # dangling -- envelope_missing_findings' territory, not drift's
        result = compute_envelope(ledger, iid)
        if not result.ok:
            continue  # a different, out-of-scope failure (e.g. no buildable geometry in the group)
        for key, target_param in model.envelope_socket.dim_params.items():
            if key not in result.values:
                continue
            expected = result.values[key]
            pd = inst.params.get(target_param)
            current = pd.value if pd is not None else None
            if current is None or abs(current - expected) > 1e-6:
                findings.append(
                    f"envelope {iid}: {iid}.{target_param} is "
                    f"{current if current is not None else 'missing'}, but its wrapped group "
                    f"({', '.join(inst.wraps)}) now implies {expected:.3f} — the group moved/resized "
                    f"since this envelope was derived; run resync_envelope on {iid} to update it")
                break  # one finding per housing is enough signal -- mirrors fit_drift_findings
    return findings


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

    # --- dfm: manufacturability heuristics read STRAIGHT off whatever thickness/draft-style params a
    # subsystem already declares by NAME (never a new opt-in flag/field — the keepout_mm lesson this
    # session: a mechanism nothing is ever taught to set is dead plumbing; this one instead activates
    # automatically the moment any subsystem happens to expose matching param names). Two sub-checks,
    # both cited to build-plan/research03aug/parametric/final_packaging_structural_design_research.md
    # section 2 — see `_DFM_RIB_RATIO_MAX`/`_DFM_DRAFT_MIN_DEG`'s own comments for the exact figures
    # and citations. Pure param arithmetic, no geometry build needed — runs over EVERY instance, not
    # gated on `healthy`, same as the `connections`/`fit` checks below. A subsystem exposing neither
    # param pair (the whole catalog today, 2026-08-04) is silently skipped — never fabricated from a
    # missing value, the same discipline `_dfm_wall_rib_params`/`_dfm_draft_param` themselves hold to. ---
    for iid, inst in ledger.instances.items():
        try:
            model = get_subsystem_model(inst.subsystem_type)
        except KeyError:
            continue
        wall_rib = _dfm_wall_rib_params(model)
        if wall_rib is not None:
            wall_name, rib_name = wall_rib
            ns = resolve_namespace(model, ledger, iid)
            wall_v, rib_v = getattr(ns, wall_name), getattr(ns, rib_name)
            if wall_v > 0 and rib_v > _DFM_RIB_RATIO_MAX * wall_v:
                issues.append(ValidationIssue(check="dfm", severity="warning",
                    message=(f"{iid} ({inst.subsystem_type})'s {rib_name} ({rib_v:.2f} mm) is "
                             f"{100.0 * rib_v / wall_v:.0f}% of {wall_name} ({wall_v:.2f} mm) — ribs/"
                             f"bosses over {_DFM_RIB_RATIO_MAX * 100:.0f}% of nominal wall sink/warp "
                             f"on cooling (Xometry/Protolabs DFM guidance, research03aug/parametric/"
                             f"final_packaging_structural_design_research.md section 2). Thin the rib "
                             f"or thicken the wall."),
                    instances=[iid]))
        draft_name = _dfm_draft_param(model)
        if draft_name is not None:
            draft_v = getattr(resolve_namespace(model, ledger, iid), draft_name)
            if draft_v < _DFM_DRAFT_MIN_DEG:
                issues.append(ValidationIssue(check="dfm", severity="warning",
                    message=(f"{iid} ({inst.subsystem_type})'s {draft_name} ({draft_v:.2f}°) is "
                             f"below the {_DFM_DRAFT_MIN_DEG}° manufacturing minimum draft angle "
                             f"(Protolabs DFM guidance, research03aug/parametric/"
                             f"final_packaging_structural_design_research.md section 2) — a molded/"
                             f"cast face this shallow won't release cleanly from its tool."),
                    instances=[iid]))

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
        # EXACT edges first: every valid (both endpoints exist AND both name a real interface —
        # _connection_resolves below, same validity bar _adjacency already applies in placement.py)
        # connection joins its two endpoints. 2026-07-27: this loop used to run over EVERY connection
        # unconditionally — a dangling connection (naming an interface that no longer exists, e.g.
        # after a subsystem's declared interfaces changed) silently exempted its own two endpoints
        # from this check (an unresolvable edge still unions them) even though the parts are, in
        # fact, not actually joined by anything real.
        for c in ledger.connections:
            if _connection_resolves(ledger, c):
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
    # Gated on TRUE CONTAINMENT (via `_inside`, the same helper the embedding check above uses), not
    # size ratio alone (2026-08-04 fix — a live gear-mesh bug exposed this: a 60-tooth/90-tooth gear
    # pair heavily overlapping by roughly half a radius has a volume ratio of (60/90)^2 ~= 0.44, under
    # the old bare `smaller < _EMBED_VOLUME_RATIO * larger` gate — so it was silently exempted from
    # `interference` and only ever produced an unrelated `connectivity` gap warning elsewhere, never
    # the finding that would have driven auto-correction. A much-smaller part TRULY INSIDE a bigger
    # one (`assembly.py`'s 2026-07-20 two-lane auto-layout cursor clustering an ordinary part near/
    # inside a big airframe body's own footprint before it's connected, or a genuinely embedded
    # component) is still legitimately embedding's territory — that case is unaffected. A
    # smaller-but-NOT-contained part merely partially overlapping a bigger one (this gear pair; two
    # differently-sized brackets that happen to clip each other) is NOT embedding's territory and must
    # not be silently exempted just because one of them is smaller.
    # Exempted by ANY declared Connection between the exact pair (regardless of its advisory
    # `kind` — a declared connection already means "this touching/overlap is intentional"), but only
    # a connection that actually RESOLVES (2026-07-27, same fix as the connectivity loop above) — a
    # dangling connection must not exempt two truly-interpenetrating parts from this check.
    #
    # 2026-08-05 fix — ALSO exempted by a FitBinding between the exact pair: found live, a standoff
    # correctly fitted around its own screw (packages/subsystems/fit.py::compute_fit, the connector
    # wraps AROUND the host by construction — that overlap is the entire point of a fit, not a
    # placement mistake) was flagged here as a false-positive "interference", every time, for every
    # fitted connector/host pair, because this exemption set only ever looked at `ledger.connections`.
    # A FitBinding is a pure wiring fact between two instance ids (packages/ledger/schema.py — no
    # frame/interface resolution needed to know it exists, unlike a Connection), so the only staleness
    # guard needed is that both ends still reference real instances (a fit whose host or connector was
    # since removed must NOT exempt an unrelated overlap that happens to reuse a freed pair of ids). ---
    connected_pairs = {frozenset((c.a.instance_id, c.b.instance_id))
                       for c in ledger.connections if _connection_resolves(ledger, c)}
    fitted_pairs = {frozenset((fb.connector_instance, fb.host_instance))
                    for fb in ledger.fit_bindings
                    if fb.connector_instance in ledger.instances and fb.host_instance in ledger.instances}
    exempt_pairs = connected_pairs | fitted_pairs
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            iid, oid = ids[a], ids[b]
            if frozenset((iid, oid)) in exempt_pairs:
                continue
            bi, bo = healthy[iid], healthy[oid]
            if bi["volume"] <= bo["volume"]:
                smaller_vol, larger_vol, smaller_bbox, larger_bbox = bi["volume"], bo["volume"], bi["bbox"], bo["bbox"]
            else:
                smaller_vol, larger_vol, smaller_bbox, larger_bbox = bo["volume"], bi["volume"], bo["bbox"], bi["bbox"]
            if (larger_vol > 0 and smaller_vol < _EMBED_VOLUME_RATIO * larger_vol
                    and _inside(smaller_bbox, larger_bbox)):
                continue  # comparable-size + TRUE containment — legitimately embedding's territory
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

    # --- region: named keep-out/keep-in volumes (packages/ledger/schema.py::Region, 2026-08-04). A
    # keep_out box intruded on by another instance's placed geometry is a real spatial conflict the
    # `interference` check above can't see (it only ever compares instance-vs-instance, never against
    # an annotation with no solid of its own) — reuses THIS FILE's own `_interferes`/`_overlap_mm`
    # overlap heuristic rather than reimplementing bbox overlap, so "intrudes" means exactly the same
    # thing here as it does there. keep_in regions are INFORMATIONAL ONLY this pass — asserting "the
    # right thing is actually inside" is a real judgment call (which OTHER instances are even relevant
    # to a given keep_in box is domain-semantic, not geometric) deliberately out of scope; this only
    # surfaces that the design intent exists, for a human/copilot to reason about, never a containment
    # verdict. The host instance itself is always exempt from its OWN region (a keep_out cavity is
    # routinely carved out of/near the host's own body on purpose; a keep_in region often names a
    # volume the host itself defines) — matches the same "the declared owner never triggers its own
    # check" shape `keepout`'s partner-exclusion above already uses. ---
    for region in ledger.regions:
        if region.kind == "keep_in":
            issues.append(ValidationIssue(check="region", severity="info",
                message=(f"{region.host_instance} declares a keep_in region '{region.label}' "
                         f"({region.dx_mm:.0f}×{region.dy_mm:.0f}×{region.dz_mm:.0f} mm) — "
                         f"informational only, this check does not verify what's actually inside it."),
                instances=[region.host_instance]))
            continue
        rbb = _region_world_bbox(ledger, region)
        if rbb is None:
            continue
        for oid in ids:
            if oid == region.host_instance:
                continue
            if _interferes(rbb, healthy[oid]["bbox"]):
                issues.append(ValidationIssue(check="region", severity="warning",
                    message=(f"{oid} ({healthy[oid]['subsystem']}) intrudes on {region.host_instance}"
                             f"'s keep_out region '{region.label}' "
                             f"({region.dx_mm:.0f}×{region.dy_mm:.0f}×{region.dz_mm:.0f} mm)."),
                    instances=[region.host_instance, oid]))

    # --- fit: a live FitBinding whose connector's stored dimensions no longer match what the host's
    # CURRENT cross-section implies (packages/subsystems/fit.py::fit_drift_findings) — the host was
    # resized after the fit was wired. Warning, drives the auto-correct loop (shouldAutoCorrect.ts) to
    # propose resync_fit — deliberately NOT export-blocking on its own; a dangling/unresolvable fit
    # (host deleted, retyped) is a stricter case and blocks via fit_gate_findings at the export gate
    # instead, mirroring coupling_gate_findings' own dangling-vs-drift split. ---
    for msg in fit_drift_findings(ledger):
        issues.append(ValidationIssue(check="fit", severity="warning", message=msg, instances=[]))

    # --- envelope_missing: a housing-family instance (declares envelope_socket, Phase 2) whose
    # `wraps` is empty or dangling -- UNGROUNDED, not just incomplete (see envelope_missing_findings's
    # own docstring for the exact failure mode this catches). ERROR severity — the same "genuinely
    # broken/ungrounded reference blocks, doesn't silently pass" class `degeneracy` above already holds
    # in this file, and the same one `packages/transport/app.py::_envelope_gate_findings` (which reuses
    # THIS SAME `envelope_missing_findings` function) enforces at the real export gate. ---
    for iid, msg in envelope_missing_findings(ledger):
        issues.append(ValidationIssue(check="envelope_missing", severity="error", message=msg, instances=[iid]))

    # --- envelope_drift: a housing whose wraps fully resolves but whose OWN stored dims no longer
    # match a fresh compute_envelope (the wrapped group moved/resized since it was derived) --
    # `_envelope_drift_findings`'s own docstring for the fit_drift_findings-mirrored dangling-vs-drift
    # split. Warning, drives the auto-correct loop's resync_envelope suggestion — deliberately NOT
    # export-blocking (that's envelope_missing's job, above). ---
    for msg in _envelope_drift_findings(ledger):
        issues.append(ValidationIssue(check="envelope_drift", severity="warning", message=msg, instances=[]))

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
