"""The rules validator — applies a ParameterDelta to the ledger deterministically (NOT an LLM).

The LLM only proposes a `ParameterDelta`; THIS code decides what happens to the source of truth:
  * forbidden target (derived.* / review.*)            -> REJECTED
  * unknown / non-tunable node                          -> REJECTED
  * HARD_LOCK parameter                                 -> REJECTED (frozen user constraint)
  * a coupled cross-field invariant would break         -> CONFLICT (no change applied)
  * value outside the RECOMMENDED range                 -> APPLIED_ADVISORY (soft bound — the AI
    judged the request reasonable in context; the range was only a design hint, not a hard cap)
  * value inside the recommended range                  -> APPLIED

Bounds are advisory (see `parameter.py`). We don't clamp — a user asking for 14 legs on a table
gets 14 legs, not "clamped to 12". Only HARD_LOCK and physical invariants (edge-distance, min-wall)
can refuse a value.

Schema enforces SHAPE; this enforces INVARIANTS. Returns a NEW ledger (event-sourcing style) + a
typed outcome; the original is never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from typing import Callable, Optional

from pydantic import ValidationError

from packages.ledger.deltas import ConnectionOp, CouplingOp, FeatureOp, InstanceOp, ParameterDelta, is_forbidden_target
from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import (
    Connection,
    Coupling,
    CouplingInput,
    CutFeature,
    Instance,
    InterfaceRef,
    MasterParametricLedger,
    Transform,
)

MIN_WALL_MM = 0.8  # general FDM/FFF floor — applies to all printed part domains
FEATURE_FIT_MARGIN_MM = 3.0  # coarse footprint-vs-host clearance for a proposed cut, mirrors
                              # MIN_WALL_MM's role as a small physical-sanity constant (not a
                              # tunable, never LLM-visible)
DEPTH_FIT_EPSILON_MM = 1e-6  # float-compare slack for the depth-vs-host-Z check below

def _set(parent, attr: str, value) -> None:
    """Assign into either an attribute (Pydantic model) or a dict key. Used for the generic
    geometry bag (Phase A) and the instance params dict (Phase G)."""
    if isinstance(parent, dict):
        parent[attr] = value
    else:
        setattr(parent, attr, value)


class ApplyStatus(str, Enum):
    APPLIED = "APPLIED"
    APPLIED_ADVISORY = "APPLIED_ADVISORY"  # applied, but outside the recommended range (soft bound)
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"


@dataclass
class CascadeEffect:
    """A companion change a CascadeRule made as a side effect of the direct edit."""
    target: str
    old_value: float
    new_value: float
    reason: str


@dataclass
class ApplyOutcome:
    status: ApplyStatus
    target: str
    # str for the one string-valued target_node (material_profile) — see apply_delta's string branch.
    old_value: float | str | None = None
    new_value: float | str | None = None
    message: str = ""
    cascades: list[CascadeEffect] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.status in (ApplyStatus.APPLIED, ApplyStatus.APPLIED_ADVISORY)


def _resolve(ledger: MasterParametricLedger, path: str):
    """Return (parent, key, current_value) for a dotted path, or (None, None, None).
    Handles typed attribute chains (`domains.structure.material_profile`) AND instance-tree paths
    (`instances.<id>.params.<name>`) uniformly by descending attrs/dicts."""
    parts = path.split(".")
    obj = ledger
    for p in parts[:-1]:
        if isinstance(obj, dict):
            if p not in obj:
                return None, None, None
            obj = obj[p]
            continue
        if not hasattr(obj, p):
            return None, None, None
        obj = getattr(obj, p)
    last = parts[-1]
    if isinstance(obj, dict):
        if last not in obj:
            return None, None, None
        return obj, last, obj[last]
    if not hasattr(obj, last):
        return None, None, None
    return obj, last, getattr(obj, last)


def resolve_path(ledger: MasterParametricLedger, path: str) -> Optional[ParameterDef]:
    """The ParameterDef currently at `path`, or None if the path doesn't resolve to one. Thin
    public wrapper over the existing _resolve() lookup — the read-side counterpart a CascadeRule
    uses to inspect sibling params before deciding what companion value (if any) to propose."""
    _, _, current = _resolve(ledger, path)
    return current if isinstance(current, ParameterDef) else None


# A cascade rule is called with (ledger BEFORE the direct edit, the target_node about to change,
# its requested_value) and returns a list of (companion_target_node, companion_new_value, reason)
# triples to ALSO apply alongside the direct edit. A rule reads OTHER current values via
# resolve_path(ledger, some_other_path) to decide whether a cascade is even needed and what value
# to propose. packages.ledger has no idea what a "subsystem" is — rules live entirely with the caller.
CascadeRule = Callable[[MasterParametricLedger, str, float], list[tuple[str, float, str]]]


def check_invariants(
    ledger: MasterParametricLedger,
    domain_checks: Optional[Callable[[MasterParametricLedger], list[str]]] = None,
) -> list[str]:
    """General cross-field invariants plus optional subsystem-specific checks.
    Phase G: reads from the instance tree (source of truth) — scans EVERY instance (not just root),
    since Item 3 (multi-instance outliner) means the mutated param may live on any instance. Generic
    over ANY param whose name ends in `thickness_mm` (the wall/skin lever bracket relies on this gate
    for — its own `_check` only covers edge-distance — while subsystems with their own explicit
    min-wall check just get a harmless duplicate finding)."""
    out: list[str] = []
    for iid, inst in (ledger.instances or {}).items():
        for name, pd in inst.params.items():
            if name.endswith("thickness_mm") and pd.value < MIN_WALL_MM:
                out.append(f"{iid}.{name} {pd.value} < min wall {MIN_WALL_MM}")
    if domain_checks is not None:
        out.extend(domain_checks(ledger))
    return out


def _apply_string_delta(
    ledger: MasterParametricLedger,
    delta: ParameterDelta,
    parent,
    attr: str,
    current: str,
    domain_checks: Optional[Callable[[MasterParametricLedger], list[str]]] = None,
) -> tuple[MasterParametricLedger, ApplyOutcome]:
    """apply_delta's counterpart for the one string-valued target_node that exists today
    (domains.structure.material_profile) — a discrete, validated CHOICE, not a numeric ParameterDef:
    no bounds/advisory concept, no HARD_LOCK (there's no ParameterDef here to lock), no cascades (a
    material swap has no geometric cascade effect the way a numeric edit does — calling a subsystem's
    own CascadeRule with a string would break its float-typed arithmetic)."""
    from packages.ledger.bom import MATERIAL_DB  # same-package import — bom.py already lives in packages/ledger

    target = delta.target_node
    requested = delta.requested_value
    if not isinstance(requested, str):
        return ledger, ApplyOutcome(
            ApplyStatus.REJECTED, target, old_value=current,
            message=f"{target} is a string-valued node — requested_value must be a string, not {requested!r}")
    if delta.set_lock is not None:
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, old_value=current,
                                    message="cannot set_lock on a string-valued node")
    if requested not in MATERIAL_DB:
        return ledger, ApplyOutcome(
            ApplyStatus.REJECTED, target, old_value=current,
            message=f"unknown material {requested!r} (known: {sorted(MATERIAL_DB)})")

    new_ledger = ledger.model_copy(deep=True)
    n_parent, n_attr, _ = _resolve(new_ledger, target)
    _set(n_parent, n_attr, requested)

    violations = check_invariants(new_ledger, domain_checks)
    if violations:
        return ledger, ApplyOutcome(ApplyStatus.CONFLICT, target, old_value=current,
                                    new_value=requested, message="; ".join(violations))
    return new_ledger, ApplyOutcome(ApplyStatus.APPLIED, target, old_value=current, new_value=requested)


def apply_delta(
    ledger: MasterParametricLedger,
    delta: ParameterDelta,
    domain_checks: Optional[Callable[[MasterParametricLedger], list[str]]] = None,
    cascade_rules: Optional[CascadeRule] = None,
) -> tuple[MasterParametricLedger, ApplyOutcome]:
    target = delta.target_node
    if is_forbidden_target(target):
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, message="LLM may not write derived/review nodes")

    parent, attr, current = _resolve(ledger, target)
    if parent is None:
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, message="unknown or non-tunable node")

    if isinstance(current, str):
        return _apply_string_delta(ledger, delta, parent, attr, current, domain_checks)

    if not isinstance(current, ParameterDef):
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, message="unknown or non-tunable node")

    if current.is_locked:
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, old_value=current.value,
                                    message="HARD_LOCK parameter is frozen")

    requested = delta.requested_value
    if not isinstance(requested, (int, float)):
        return ledger, ApplyOutcome(ApplyStatus.REJECTED, target, old_value=current.value,
                                    message=f"{target} is a numeric node — requested_value must be a number, not {requested!r}")

    lo, hi = current.bounds
    outside_recommended = not (lo <= requested <= hi)

    # Cascades: computed against the PRE-edit ledger (so a rule sees the "before" state), applied
    # atomically alongside the direct edit below, and only kept if the result passes invariants.
    cascade_effects: list[CascadeEffect] = []
    proposed = cascade_rules(ledger, target, requested) if cascade_rules is not None else []

    new_ledger = ledger.model_copy(deep=True)
    n_parent, n_attr, n_pd = _resolve(new_ledger, target)
    updated = n_pd.with_value(requested)
    if delta.set_lock is not None:
        updated = updated.model_copy(update={"lock_state": LockState(delta.set_lock)})
    _set(n_parent, n_attr, updated)

    for c_target, c_value, c_reason in proposed:
        c_parent, c_attr, c_current = _resolve(new_ledger, c_target)
        if c_parent is None or not isinstance(c_current, ParameterDef):
            continue  # stale/renamed path — the rule author's bug, must not crash the mutation
        if c_current.is_locked:
            continue  # HARD_LOCK is frozen — a cascade must never override it, same as the direct edit
        _set(c_parent, c_attr, c_current.with_value(c_value))
        cascade_effects.append(CascadeEffect(target=c_target, old_value=c_current.value,
                                             new_value=c_value, reason=c_reason))

    violations = check_invariants(new_ledger, domain_checks)
    if violations:
        return ledger, ApplyOutcome(ApplyStatus.CONFLICT, target, old_value=current.value,
                                    new_value=requested, message="; ".join(violations))

    if outside_recommended:
        msg = f"{requested} is outside recommended range [{lo}, {hi}] — applied on copilot judgment"
        return new_ledger, ApplyOutcome(ApplyStatus.APPLIED_ADVISORY, target,
                                        old_value=current.value, new_value=requested, message=msg,
                                        cascades=cascade_effects)
    return new_ledger, ApplyOutcome(ApplyStatus.APPLIED, target,
                                    old_value=current.value, new_value=requested, message="",
                                    cascades=cascade_effects)


# --- FeatureOp: the rules validator for hole/pocket/slot cuts -----------------------------------
#
# apply_feature_op is the FeatureOp counterpart to apply_delta above. It deliberately takes
# `build_part` as an INJECTED callable — exactly like `domain_checks`/`cascade_rules` above — rather
# than importing packages.subsystems / build123d directly. packages/ledger stays pure data + pure
# validation (see packages/ledger/CLAUDE.md: "No OCCT, no solver, no LLM, no I/O in this package").
# The caller (which already knows how to resolve a subsystem's geometry_builder, e.g.
# packages/transport/app.py or packages/agents/runtime.py) supplies
# `build_part(ledger, instance_id) -> TaggedPart-shaped object` (anything exposing
# `.solid.bounding_box()`, in practice `get_subsystem(inst.subsystem_type).geometry_builder`).
# Required for add_feature/update_feature (both need a real geometry build to resolve "through" and
# to validate fit / single-solid-ness); ignored for remove_feature, which is pure ledger surgery.


@dataclass
class FeatureOpOutcome:
    """FeatureOp's analog of ApplyOutcome. Doesn't reuse ApplyOutcome's target_node/requested_value
    shape directly — a feature op's payload (id/kind/shape/depth/position) doesn't map onto a single
    float, so this carries the resolved CutFeature instead."""

    status: ApplyStatus
    instance_id: str
    feature: Optional[CutFeature] = None  # the added/updated feature, or the one just removed
    message: str = ""

    @property
    def changed(self) -> bool:
        return self.status is ApplyStatus.APPLIED


def _next_feature_id(instance: Instance, instance_id: str) -> str:
    """Deterministic, collision-free id for a NEW feature on `instance`. The LLM never invents an id
    for add_feature (per FeatureOp's docstring) — this is the one place a fresh id is minted."""
    existing = {f.id for f in instance.cut_features}
    n = len(instance.cut_features)
    candidate = f"{instance_id}_cut{n}"
    while candidate in existing:
        n += 1
        candidate = f"{instance_id}_cut{n}"
    return candidate


def _with_cut_features(
    ledger: MasterParametricLedger, instance_id: str, features: list[CutFeature],
) -> MasterParametricLedger:
    """Immutable update of one instance's `cut_features` list — never mutate in place."""
    inst = ledger.instances[instance_id]
    new_instances = dict(ledger.instances)
    new_instances[instance_id] = inst.model_copy(update={"cut_features": features})
    return ledger.model_copy(update={"instances": new_instances})


def _fit_violation(built_part, candidate: CutFeature) -> Optional[str]:
    """Coarse footprint-vs-host-extent check in host-local X/Y (does not account for off-center
    placement pushing the feature past an edge — a later stage can tighten this). Returns a
    rejection message, or None if the candidate's footprint plausibly fits."""
    bbox = built_part.solid.bounding_box()
    host_x, host_y = float(bbox.size.X), float(bbox.size.Y)
    if candidate.shape == "circle":
        fp_x = fp_y = candidate.dia_mm
    else:
        fp_x, fp_y = candidate.length_mm, candidate.width_mm
    if fp_x > host_x - FEATURE_FIT_MARGIN_MM or fp_y > host_y - FEATURE_FIT_MARGIN_MM:
        return (f"feature footprint ({fp_x:.1f} x {fp_y:.1f} mm) does not fit within the host's "
                f"{host_x:.1f} x {host_y:.1f} mm footprint (margin {FEATURE_FIT_MARGIN_MM} mm)")
    return None


def _depth_violation(built_part, depth_mm: float) -> Optional[str]:
    """A cut's `depth_mm` must never exceed the host's REAL Z-extent. A real OCCT boolean subtract
    can only remove material that is actually solid there — it is physically bounded by the host's
    own thickness no matter what `depth_mm` claims — so a stored `depth_mm` deeper than that thickness
    would silently inflate `swept_volume_mm3`'s analytic mass/volume accounting
    (`packages/subsystems/cut_features.py`) past what any real cut could remove: a grounded-looking but
    wrong number, exactly what Inversion #1 forbids. A `through=True` cut never trips this — its
    `depth_mm` IS the host's own measured Z-extent (see the `through` branch above), so it always
    compares equal (within float slack), never greater."""
    host_z = float(built_part.solid.bounding_box().size.Z)
    if depth_mm > host_z + DEPTH_FIT_EPSILON_MM:
        return (f"depth {depth_mm:.2f} mm exceeds the host's real {host_z:.2f} mm material "
                f"thickness — use through=True for a full-penetration cut, or reduce depth_mm")
    return None


def apply_feature_op(
    ledger: MasterParametricLedger,
    op: FeatureOp,
    build_part: Optional[Callable[[MasterParametricLedger, str], object]] = None,
) -> tuple[MasterParametricLedger, FeatureOpOutcome]:
    """Apply one FeatureOp (add/update/remove a hole/pocket/slot) to `ledger`. Returns a NEW ledger
    (event-sourcing style, same convention as apply_delta) + a typed outcome; the original is never
    mutated. See the module-level comment above for why `build_part` is an injected callable."""
    inst = ledger.instances.get(op.instance_id)
    if inst is None:
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message=f"unknown instance_id {op.instance_id!r}")

    if op.op == "remove_feature":
        if op.feature_id is None:
            return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                            message="remove_feature requires feature_id")
        target = next((f for f in inst.cut_features if f.id == op.feature_id), None)
        if target is None:
            return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                            message=f"unknown feature_id {op.feature_id!r}")
        remaining = [f for f in inst.cut_features if f.id != op.feature_id]
        new_ledger = _with_cut_features(ledger, op.instance_id, remaining)
        return new_ledger, FeatureOpOutcome(ApplyStatus.APPLIED, op.instance_id, feature=target,
                                            message=f"removed {target.id}")

    if op.op not in ("add_feature", "update_feature"):
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message=f"unknown op {op.op!r}")

    # update_feature: look up the feature it targets FIRST — everything below merges op fields on
    # top of it (a partial update, not a full replace requiring every field re-specified). NOTE:
    # x_mm/y_mm are the one exception — FeatureOp declares them as plain (non-Optional) floats
    # defaulting to 0.0, so there is no "not supplied" sentinel for position; an update always takes
    # op.x_mm/op.y_mm as-is. A caller doing a size-only update must echo the feature's current
    # position back on the op.
    existing_feature: Optional[CutFeature] = None
    if op.op == "update_feature":
        if op.feature_id is None:
            return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                            message="update_feature requires feature_id")
        existing_feature = next((f for f in inst.cut_features if f.id == op.feature_id), None)
        if existing_feature is None:
            return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                            message=f"unknown feature_id {op.feature_id!r}")

    kind = op.kind if op.kind is not None else (existing_feature.kind if existing_feature else None)
    shape = op.shape if op.shape is not None else (existing_feature.shape if existing_feature else None)
    if kind is None or shape is None:
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message=f"{op.op} requires kind and shape")

    dia_mm = op.dia_mm if op.dia_mm is not None else (existing_feature.dia_mm if existing_feature else None)
    length_mm = (op.length_mm if op.length_mm is not None
                else (existing_feature.length_mm if existing_feature else None))
    width_mm = (op.width_mm if op.width_mm is not None
               else (existing_feature.width_mm if existing_feature else None))

    if shape == "circle" and dia_mm is None:
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message="circle cut requires dia_mm")
    if shape == "rect" and (length_mm is None or width_mm is None):
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message="rect cut requires length_mm and width_mm")

    if build_part is None:
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message=f"{op.op} needs a geometry builder to resolve depth "
                                                f"and validate fit")

    try:
        built = build_part(ledger, op.instance_id)  # the instance's CURRENT geometry (pre-candidate)
    except Exception as exc:
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message=f"could not build host geometry: {exc}")
    if built is None:
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message="instance has no buildable geometry")

    if op.through:
        # The TRUE host Z-extent -- NOT inflated by a robustness margin. `depth_mm` is the ledger's
        # grounded fact for this feature and feeds `swept_volume_mm3`'s analytic mass/volume
        # accounting directly (packages/subsystems/cut_features.py) with no OCCT re-derivation, so
        # padding it here (as an earlier version did, `z_extent * 1.5`) silently overcounts removed
        # material by exactly that factor. Any OCCT-robustness margin a "through" cut's cutter needs
        # to reliably clear the host's far face despite floating-point boundary coincidence belongs
        # ONLY inside `apply_cut_features`'s cutter construction (see its OVERHANG_MM), never baked
        # into this stored depth.
        depth_mm = float(built.solid.bounding_box().size.Z)
    elif op.depth_mm is not None:
        if op.depth_mm <= 0:
            return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                            message="depth_mm must be positive")
        depth_mm = op.depth_mm
    elif existing_feature is not None:
        depth_mm = existing_feature.depth_mm  # partial update: depth unchanged
    else:
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                        message=f"{op.op} requires depth_mm or through=True")

    # Depth-vs-host-Z sanity BEFORE constructing the candidate — a depth deeper than the host's real
    # material (see `_depth_violation`'s docstring) is exactly as physically nonsensical as an
    # oversized XY footprint and must never reach the ledger / swept-volume accounting.
    depth_msg = _depth_violation(built, depth_mm)
    if depth_msg is not None:
        return ledger, FeatureOpOutcome(ApplyStatus.CONFLICT, op.instance_id, message=depth_msg)

    feature_id = existing_feature.id if existing_feature is not None else _next_feature_id(inst, op.instance_id)

    try:
        candidate = CutFeature(id=feature_id, kind=kind, shape=shape, dia_mm=dia_mm,
                               length_mm=length_mm, width_mm=width_mm, depth_mm=depth_mm,
                               x_mm=op.x_mm, y_mm=op.y_mm)
    except Exception as exc:
        return ledger, FeatureOpOutcome(ApplyStatus.REJECTED, op.instance_id, message=str(exc))

    fit_msg = _fit_violation(built, candidate)
    if fit_msg is not None:
        return ledger, FeatureOpOutcome(ApplyStatus.CONFLICT, op.instance_id, message=fit_msg)

    if existing_feature is not None:
        candidate_features = [candidate if f.id == existing_feature.id else f for f in inst.cut_features]
    else:
        candidate_features = list(inst.cut_features) + [candidate]

    # VALIDATE BEFORE COMMITTING: re-build with the candidate feature set appended. `build_part`
    # (== a subsystem's registered geometry_builder) already applies cut_features generically
    # (packages/subsystems/__init__.py's `_build` closure calls apply_cut_features), so this reuses
    # that wiring instead of duplicating it — and its single-solid check raises ValueError, which we
    # convert to a CONFLICT rather than let propagate into the ledger.
    probe_ledger = _with_cut_features(ledger, op.instance_id, candidate_features)
    try:
        build_part(probe_ledger, op.instance_id)
    except ValueError as exc:
        return ledger, FeatureOpOutcome(ApplyStatus.CONFLICT, op.instance_id, message=str(exc))

    new_ledger = _with_cut_features(ledger, op.instance_id, candidate_features)
    verb = "added" if op.op == "add_feature" else "updated"
    return new_ledger, FeatureOpOutcome(ApplyStatus.APPLIED, op.instance_id, feature=candidate,
                                        message=f"{verb} {candidate.id} (depth {depth_mm:.2f} mm)")


# --- InstanceOp: the rules validator for multi-instance assembly composition ---------------------
#
# apply_instance_op is the InstanceOp counterpart to apply_delta / apply_feature_op above. Same
# purity boundary, same injection style: packages/ledger has NO idea what a "subsystem" is, so
# everything that needs the real subsystem registry (validating a name, materializing a fresh
# Instance's default params, re-converging an assembly-template's children) is an INJECTED callable
# the caller (packages/transport/app.py or packages/agents/runtime.py, which already imports
# packages.subsystems) binds to the real thing:
#   - `known_subsystem_types`: frozenset(SUBSYSTEM_REGISTRY) — just names, not the registry itself.
#   - `seed_defaults(subsystem_type, instance_id, parent_id) -> Instance` — bound to
#     `packages.subsystems.base.seed_instance(get_subsystem_model(subsystem_type), instance_id,
#     parent_id=parent_id)`. Takes the subsystem_type NAME (not the `Subsystem` model, which
#     packages.ledger must never import) so this function stays entirely within the ledger's typed
#     seam.
#   - `reconcile(ledger, instance_id) -> MasterParametricLedger` — bound to
#     `packages.subsystems.assembly_template.reconcile_children`; a safe no-op for a non-assembly-
#     template instance, so callers that don't care can simply always pass it (or omit it — None is
#     accepted and skipped, e.g. for tests that don't need assembly-template coverage).


@dataclass
class InstanceOpOutcome:
    """InstanceOp's analog of ApplyOutcome/FeatureOpOutcome. Carries the resolved Instance (the one
    just added, removed, or moved) rather than a single float/CutFeature."""

    status: ApplyStatus
    instance_id: Optional[str]
    instance: Optional[Instance] = None  # the added/removed/moved instance — for move_instance, its
                                          # POST-move state (matches add_instance's "instance = the
                                          # resulting state" convention)
    removed_connection_ids: list[str] = field(default_factory=list)  # remove_instance ONLY: ids of
                                          # connections cascade-removed because they referenced the
                                          # removed instance — the endpoint appends a CONNECTION_REMOVED
                                          # event for each so the cascade survives replay (2026-07-19).
    removed_coupling_ids: list[str] = field(default_factory=list)  # remove_instance ONLY: ids of
                                          # couplings cascade-removed because they referenced the removed
                                          # instance, either as target_instance OR as an input's
                                          # from_instance (Phase 2b, 2026-07-19) — see apply_instance_op's
                                          # remove_instance branch for why the check is wider than
                                          # removed_connection_ids's.
    previous_instance: Optional[Instance] = None  # move_instance ONLY: the PRE-move state, needed so
                                                    # the frontend can Undo a move by moving it back.
                                                    # add_instance/remove_instance leave this None.
    message: str = ""

    @property
    def changed(self) -> bool:
        return self.status is ApplyStatus.APPLIED


def resolve_instance_parent(ledger: MasterParametricLedger, parent_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Resolve the effective parent for a new instance. Parts are a FLAT set brought into a file
    (2026-07-04) — there is no root/seed part and no auto-parenting under whatever happened to be
    added first. `parent_id` omitted -> top-level (`None`). `parent_id` given and it names a real
    instance -> honored (real use: explicit REST parenting, assembly-template children). `parent_id`
    given but unknown (e.g. the LLM guessing "root" against an empty or unfamiliar file) -> falls
    back to top-level rather than rejecting the whole op — a guessed reference is not a physical
    invariant, and this codebase only hard-stops on those (edge-distance, min-wall, HARD_LOCK, …).

    Returns `(effective_parent_id, note)`; `note` is set only when the caller's `parent_id` was
    given but didn't resolve, so the outcome message can say what actually happened instead of
    silently reinterpreting the request. Shared by `packages.subsystems.add_instance` and
    `apply_instance_op` below so this rule can't drift between the two entry points that add an
    instance."""
    if parent_id is None:
        return None, None
    if parent_id in ledger.instances:
        return parent_id, None
    return None, f"parent {parent_id!r} not found — added as a top-level part"


def _next_instance_id(ledger: MasterParametricLedger, subsystem_type: str) -> str:
    """Mirrors `packages/transport/app.py::create_instance`'s exact "{subsystem_type}_{n}" scheme —
    the LLM never invents an id for add_instance when it omits one, just like FeatureOp's add_feature."""
    n = 1
    candidate = f"{subsystem_type}_{n}"
    while candidate in ledger.instances:
        n += 1
        candidate = f"{subsystem_type}_{n}"
    return candidate


def apply_instance_op(
    ledger: MasterParametricLedger,
    op: InstanceOp,
    known_subsystem_types: frozenset[str],
    seed_defaults: Optional[Callable[[str, str, Optional[str]], Instance]] = None,
    reconcile: Optional[Callable[[MasterParametricLedger, str], MasterParametricLedger]] = None,
) -> tuple[MasterParametricLedger, InstanceOpOutcome]:
    """Apply one InstanceOp (add/remove an instance of an EXISTING subsystem type) to `ledger`.
    Returns a NEW ledger (event-sourcing style, same convention as apply_delta/apply_feature_op) + a
    typed outcome; the original is never mutated. See the module-level comment above for the
    injected-callable shapes."""
    if op.op == "remove_instance":
        instance_id = op.instance_id
        if instance_id is None:
            return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, None,
                                             message="remove_instance requires instance_id")
        target = ledger.instances.get(instance_id)
        if target is None:
            return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, instance_id,
                                             message=f"unknown instance id {instance_id!r}")
        children = [i for i, inst in ledger.instances.items() if inst.parent_id == instance_id]
        if children:
            return ledger, InstanceOpOutcome(
                ApplyStatus.REJECTED, instance_id,
                message=f"instance {instance_id!r} has children {children} — remove them first")
        # Any childless part is removable — there's no root/seed part carve-out (2026-07-04: parts
        # are a flat set brought into a file). The children-check above is the only guard needed:
        # it already prevents orphaning a template's or an explicitly-parented instance's dependents.
        new_instances = dict(ledger.instances)
        del new_instances[instance_id]
        # CASCADE-remove connections that reference the removed instance — otherwise they dangle, and
        # because instance ids are reused (lowest-free), a later add of the SAME subsystem type would
        # silently resurrect a stale connection onto an unrelated new part (wrong mate geometry + a
        # false "joined" verdict that persists on replay) — 2026-07-19 review. Symmetric with the
        # children guard above; the ids are returned so the endpoint persists a CONNECTION_REMOVED
        # event for each (the cascade must survive replay, not just this fold).
        removed_conn_ids = [c.id for c in ledger.connections
                            if c.a.instance_id == instance_id or c.b.instance_id == instance_id]
        # CASCADE-remove couplings that reference the removed instance — WIDER check than connections:
        # a Coupling can reference the removed instance either as its `target_instance` OR as the
        # `from_instance` of ANY of its `inputs`. Same id-reuse hazard as the connection cascade above
        # (2026-07-19 review) but worse if missed: because instance ids are reused (lowest-free, see
        # _next_instance_id), a later add of the same subsystem_type would silently make a stale
        # coupling's source or target resolve against an UNRELATED NEW instance, fabricating a
        # physically wrong but plausible-looking derived load instead of blocking as "unknown".
        removed_coupling_ids = [
            c.id for c in ledger.couplings
            if c.target_instance == instance_id
            or any(ci.from_instance == instance_id for ci in c.inputs.values())
        ]
        update: dict = {"instances": new_instances}
        if removed_conn_ids:
            drop = set(removed_conn_ids)
            update["connections"] = [c for c in ledger.connections if c.id not in drop]
        if removed_coupling_ids:
            drop_c = set(removed_coupling_ids)
            update["couplings"] = [c for c in ledger.couplings if c.id not in drop_c]
        new_ledger = ledger.model_copy(update=update)
        return new_ledger, InstanceOpOutcome(ApplyStatus.APPLIED, instance_id, instance=target,
                                             removed_connection_ids=removed_conn_ids,
                                             removed_coupling_ids=removed_coupling_ids,
                                             message=f"removed {instance_id}")

    if op.op == "move_instance":
        instance_id = op.instance_id
        if instance_id is None:
            return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, None,
                                             message="move_instance requires instance_id")
        target = ledger.instances.get(instance_id)
        if target is None:
            return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, instance_id,
                                             message=f"unknown instance id {instance_id!r}")

        # Position is REQUIRED, all three together — unlike add_instance, there is no sensible
        # auto-layout fallback for an explicit move request (see InstanceOp's docstring).
        axes = (op.x_mm, op.y_mm, op.z_mm)
        n_given = sum(a is not None for a in axes)
        if n_given != 3:
            return ledger, InstanceOpOutcome(
                ApplyStatus.REJECTED, instance_id,
                message="move_instance requires x_mm/y_mm/z_mm (all three together)")

        # Rotation follows add_instance's all-or-nothing convention, but here omitting it means
        # "keep the instance's CURRENT rotation" rather than "reject" — an existing instance being
        # moved has a real current rotation that must not be silently zeroed.
        rotations = (op.rx_deg, op.ry_deg, op.rz_deg)
        n_rot_given = sum(a is not None for a in rotations)
        if n_rot_given not in (0, 3):
            return ledger, InstanceOpOutcome(
                ApplyStatus.REJECTED, instance_id,
                message="rx_deg/ry_deg/rz_deg must be given all together or not at all (partial "
                        "rotation would silently default the missing axes to 0)")

        current_transform = target.transform or Transform()
        if n_rot_given == 3:
            rx, ry, rz = op.rx_deg, op.ry_deg, op.rz_deg
        else:
            rx, ry, rz = current_transform.rx_deg, current_transform.ry_deg, current_transform.rz_deg

        new_transform = Transform(x_mm=op.x_mm, y_mm=op.y_mm, z_mm=op.z_mm, rx_deg=rx, ry_deg=ry, rz_deg=rz)
        new_instance = target.model_copy(update={"transform": new_transform})
        new_instances = dict(ledger.instances)
        new_instances[instance_id] = new_instance
        new_ledger = ledger.model_copy(update={"instances": new_instances})
        return new_ledger, InstanceOpOutcome(ApplyStatus.APPLIED, instance_id, instance=new_instance,
                                             previous_instance=target, message=f"moved {instance_id}")

    if op.op != "add_instance":
        return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                         message=f"unknown op {op.op!r}")

    if not op.subsystem_type:
        return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                         message="add_instance requires subsystem_type")
    if op.subsystem_type not in known_subsystem_types:
        return ledger, InstanceOpOutcome(
            ApplyStatus.REJECTED, op.instance_id,
            message=f"unknown subsystem_type {op.subsystem_type!r} — must be an already-registered "
                    f"part type")

    if op.instance_id is not None and op.instance_id in ledger.instances:
        return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, op.instance_id,
                                         message=f"instance id {op.instance_id!r} already exists")
    instance_id = op.instance_id if op.instance_id is not None else _next_instance_id(ledger, op.subsystem_type)

    parent_id, parent_note = resolve_instance_parent(ledger, op.parent_id)

    # Transform is all-or-nothing: a partial spec (e.g. only x_mm) would silently default the other
    # axes to 0.0, which could place the instance somewhere the LLM never intended.
    axes = (op.x_mm, op.y_mm, op.z_mm)
    n_given = sum(a is not None for a in axes)
    if n_given not in (0, 3):
        return ledger, InstanceOpOutcome(
            ApplyStatus.REJECTED, instance_id,
            message="x_mm/y_mm/z_mm must be given all together or not at all (partial transform "
                    "would silently default the missing axes to 0)")

    # Rotation follows the same all-or-nothing convention as position, PLUS a dependency: rotation
    # may only be given together with an explicit position. auto-layout (instance_world_offsets)
    # computes a placement from the part's UNROTATED bounding box, so it has no way to account for a
    # rotated part — rotation without an explicit position is rejected rather than silently ignored.
    rotations = (op.rx_deg, op.ry_deg, op.rz_deg)
    n_rot_given = sum(a is not None for a in rotations)
    if n_rot_given not in (0, 3):
        return ledger, InstanceOpOutcome(
            ApplyStatus.REJECTED, instance_id,
            message="rx_deg/ry_deg/rz_deg must be given all together or not at all (partial "
                    "rotation would silently default the missing axes to 0)")
    if n_rot_given == 3 and n_given != 3:
        return ledger, InstanceOpOutcome(
            ApplyStatus.REJECTED, instance_id,
            message="rotation (rx_deg/ry_deg/rz_deg) requires an explicit position "
                    "(x_mm/y_mm/z_mm) — auto-layout has no way to place a rotated part from its "
                    "unrotated bounding box")

    if seed_defaults is None:
        return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, instance_id,
                                         message="add_instance needs a seed_defaults callable to "
                                                 "materialize the new instance's default params")
    try:
        new_instance = seed_defaults(op.subsystem_type, instance_id, parent_id)
    except Exception as exc:
        return ledger, InstanceOpOutcome(ApplyStatus.REJECTED, instance_id,
                                         message=f"could not seed instance defaults: {exc}")

    if n_given == 3:
        new_instance = new_instance.model_copy(
            update={"transform": Transform(
                x_mm=op.x_mm, y_mm=op.y_mm, z_mm=op.z_mm,
                rx_deg=op.rx_deg or 0.0, ry_deg=op.ry_deg or 0.0, rz_deg=op.rz_deg or 0.0)})

    new_instances = dict(ledger.instances)
    new_instances[instance_id] = new_instance
    new_ledger = ledger.model_copy(update={"instances": new_instances})

    if reconcile is not None:
        new_ledger = reconcile(new_ledger, instance_id)

    message = f"added {instance_id} ({op.subsystem_type})"
    if parent_note:
        message += f" — {parent_note}"
    return new_ledger, InstanceOpOutcome(ApplyStatus.APPLIED, instance_id,
                                         instance=new_ledger.instances[instance_id],
                                         message=message)


@dataclass
class ConnectionOpOutcome:
    """ConnectionOp's analog of InstanceOpOutcome. Carries the resolved Connection (added or removed)."""

    status: "ApplyStatus"
    connection_id: Optional[str]
    connection: Optional[Connection] = None
    message: str = ""

    @property
    def changed(self) -> bool:
        return self.status is ApplyStatus.APPLIED


def _next_connection_id(ledger: MasterParametricLedger) -> str:
    existing = {c.id for c in ledger.connections}
    n = 1
    while f"conn_{n}" in existing:
        n += 1
    return f"conn_{n}"


def apply_connection_op(
    ledger: MasterParametricLedger,
    op: ConnectionOp,
    interfaces_of: Callable[[str], frozenset[str]],
) -> tuple[MasterParametricLedger, "ConnectionOpOutcome"]:
    """Apply one ConnectionOp (add/remove a typed interface-to-interface join). Returns a NEW ledger +
    outcome; original never mutated (same event-sourcing convention as apply_instance_op).

    This package stays registry-free (`packages/ledger/CLAUDE.md`) — `interfaces_of(subsystem_type)`
    is injected (frozenset of declared interface names for a type) so the op can REJECT an interface
    the part doesn't declare, without importing the subsystem registry here. The LLM must only wire
    interfaces that exist (listed in the part-types menu); a hallucinated interface fails loudly."""
    if op.op == "remove_connection":
        if not op.id:
            return ledger, ConnectionOpOutcome(ApplyStatus.REJECTED, None,
                                               message="remove_connection requires id")
        match = next((c for c in ledger.connections if c.id == op.id), None)
        if match is None:
            return ledger, ConnectionOpOutcome(ApplyStatus.REJECTED, op.id,
                                               message=f"unknown connection id {op.id!r}")
        new = ledger.model_copy(update={"connections": [c for c in ledger.connections if c.id != op.id]})
        return new, ConnectionOpOutcome(ApplyStatus.APPLIED, op.id, connection=match,
                                        message=f"removed connection {op.id}")

    if op.op != "add_connection":
        return ledger, ConnectionOpOutcome(ApplyStatus.REJECTED, op.id, message=f"unknown op {op.op!r}")

    # add_connection: all four endpoints required
    missing = [f for f in ("a_instance", "a_interface", "b_instance", "b_interface") if getattr(op, f) is None]
    if missing:
        return ledger, ConnectionOpOutcome(ApplyStatus.REJECTED, op.id,
                                           message=f"add_connection requires {', '.join(missing)}")
    if op.id is not None and any(c.id == op.id for c in ledger.connections):
        return ledger, ConnectionOpOutcome(ApplyStatus.REJECTED, op.id,
                                           message=f"connection id {op.id!r} already exists")
    if op.a_instance == op.b_instance:
        return ledger, ConnectionOpOutcome(ApplyStatus.REJECTED, op.id,
                                           message="a part cannot connect to itself")
    # both instances must exist and declare the named interface
    for iid, iface, side in ((op.a_instance, op.a_interface, "a"), (op.b_instance, op.b_interface, "b")):
        inst = ledger.instances.get(iid)
        if inst is None:
            return ledger, ConnectionOpOutcome(ApplyStatus.REJECTED, op.id,
                                               message=f"endpoint {side}: unknown instance {iid!r}")
        if iface not in interfaces_of(inst.subsystem_type):
            declared = sorted(interfaces_of(inst.subsystem_type))
            return ledger, ConnectionOpOutcome(
                ApplyStatus.REJECTED, op.id,
                message=f"endpoint {side}: {inst.subsystem_type} has no interface {iface!r} "
                        f"(declares: {declared or 'none'})")

    conn_id = op.id if op.id is not None else _next_connection_id(ledger)
    conn = Connection(
        id=conn_id,
        a=InterfaceRef(instance_id=op.a_instance, interface=op.a_interface),
        b=InterfaceRef(instance_id=op.b_instance, interface=op.b_interface),
        kind=op.kind or "mate",
        gap_mm=op.gap_mm or 0.0,
    )
    new = ledger.model_copy(update={"connections": [*ledger.connections, conn]})
    return new, ConnectionOpOutcome(ApplyStatus.APPLIED, conn_id, connection=conn,
                                    message=f"connected {op.a_instance}.{op.a_interface} <-> "
                                            f"{op.b_instance}.{op.b_interface}")


@dataclass
class CouplingOpOutcome:
    """CouplingOp's analog of ConnectionOpOutcome. Carries the resolved Coupling (added or removed)."""

    status: ApplyStatus
    coupling_id: Optional[str]
    coupling: Optional[Coupling] = None
    message: str = ""

    @property
    def changed(self) -> bool:
        return self.status is ApplyStatus.APPLIED


def _next_coupling_id(ledger: MasterParametricLedger) -> str:
    existing = {c.id for c in ledger.couplings}
    n = 1
    while f"coupling_{n}" in existing:
        n += 1
    return f"coupling_{n}"


def apply_coupling_op(
    ledger: MasterParametricLedger,
    op: CouplingOp,
    known_relations: frozenset[str],
    inputs_of: Callable[[str], frozenset[str]],
) -> tuple[MasterParametricLedger, CouplingOpOutcome]:
    """Apply one CouplingOp (add/remove a typed load coupling wiring a target's load to a registered
    relation over source parts/duty). Returns a NEW ledger + outcome; original never mutated (same
    event-sourcing convention as apply_connection_op).

    This package stays registry-free (`packages/ledger/CLAUDE.md`) — `known_relations` (names only)
    and `inputs_of(relation) -> frozenset[str]` (a relation's declared input quantity names) are
    injected so this function can validate a relation/its inputs without importing
    `packages.couplings` here. `inputs_of` is ONLY called after confirming `op.relation` is a member
    of `known_relations` — never on a name that hasn't already been validated. The LLM must only wire
    a relation that exists in the registry (Inversion #1 — it never authors the physics); a
    hallucinated relation name fails loudly."""
    if op.op == "remove_coupling":
        if not op.id:
            return ledger, CouplingOpOutcome(ApplyStatus.REJECTED, None,
                                             message="remove_coupling requires id")
        match = next((c for c in ledger.couplings if c.id == op.id), None)
        if match is None:
            return ledger, CouplingOpOutcome(ApplyStatus.REJECTED, op.id,
                                             message=f"unknown coupling id {op.id!r}")
        new = ledger.model_copy(update={"couplings": [c for c in ledger.couplings if c.id != op.id]})
        return new, CouplingOpOutcome(ApplyStatus.APPLIED, op.id, coupling=match,
                                      message=f"removed coupling {op.id}")

    if op.op != "add_coupling":
        return ledger, CouplingOpOutcome(ApplyStatus.REJECTED, op.id, message=f"unknown op {op.op!r}")

    # add_coupling: target_instance and relation are required
    missing_fields = [f for f in ("target_instance", "relation") if getattr(op, f) is None]
    if missing_fields:
        return ledger, CouplingOpOutcome(ApplyStatus.REJECTED, op.id,
                                         message=f"add_coupling requires {', '.join(missing_fields)}")
    if op.id is not None and any(c.id == op.id for c in ledger.couplings):
        return ledger, CouplingOpOutcome(ApplyStatus.REJECTED, op.id,
                                         message=f"coupling id {op.id!r} already exists")
    if op.target_instance not in ledger.instances:
        return ledger, CouplingOpOutcome(ApplyStatus.REJECTED, op.id,
                                         message=f"unknown instance {op.target_instance!r}")
    if op.relation not in known_relations:
        return ledger, CouplingOpOutcome(
            ApplyStatus.REJECTED, op.id,
            message=f"unknown relation {op.relation!r} — must be a registered relation "
                    f"(available: {sorted(known_relations)})")

    required = inputs_of(op.relation)
    names = [i.name for i in op.inputs]
    given = set(names)
    if len(names) != len(given):
        dupes = sorted({n for n in names if names.count(n) > 1})
        return ledger, CouplingOpOutcome(
            ApplyStatus.REJECTED, op.id,
            message=f"duplicate input name(s) {dupes} — each relation input may be wired exactly once "
                    f"(a repeat silently discards an earlier wiring, which this rejects instead)")
    missing = required - given
    extra = given - required
    if missing or extra:
        clauses = []
        if missing:
            clauses.append(f"missing {sorted(missing)}")
        if extra:
            clauses.append(f"unexpected {sorted(extra)}")
        return ledger, CouplingOpOutcome(
            ApplyStatus.REJECTED, op.id,
            message=f"relation {op.relation!r} needs inputs {sorted(required)} — " + ", ".join(clauses))

    # A sourced input's from_instance/from_param must reference something real RIGHT NOW — the same
    # loud-fail-on-a-typo standard target_instance already gets above. Left unchecked, a hallucinated
    # source silently persists as APPLIED and only degrades to "unknown" much later, at resolve time
    # (packages/couplings/resolve.py) — technically safe (unknown still blocks export) but a
    # misleading immediate signal that the wiring succeeded when it didn't (2026-07-19 review).
    for item in op.inputs:
        if item.from_instance is None:
            continue
        src = ledger.instances.get(item.from_instance)
        if src is None:
            return ledger, CouplingOpOutcome(
                ApplyStatus.REJECTED, op.id,
                message=f"input {item.name!r} sources from unknown instance {item.from_instance!r}")
        if item.from_param not in src.params:
            return ledger, CouplingOpOutcome(
                ApplyStatus.REJECTED, op.id,
                message=f"input {item.name!r} sources from {item.from_instance!r}.{item.from_param!r}, "
                        f"which has no such param (has: {sorted(src.params)})")

    try:
        coupling_inputs = {
            item.name: CouplingInput(value=item.value, from_instance=item.from_instance,
                                     from_param=item.from_param)
            for item in op.inputs
        }
    except ValidationError as exc:
        return ledger, CouplingOpOutcome(ApplyStatus.REJECTED, op.id, message=str(exc))

    coupling_id = op.id if op.id is not None else _next_coupling_id(ledger)
    coupling = Coupling(
        id=coupling_id,
        target_instance=op.target_instance,
        relation=op.relation,
        inputs=coupling_inputs,
    )
    new_ledger = ledger.model_copy(update={"couplings": [*ledger.couplings, coupling]})
    return new_ledger, CouplingOpOutcome(ApplyStatus.APPLIED, coupling.id, coupling=coupling,
                                         message=f"coupled {op.target_instance} <- {op.relation}(...)")
