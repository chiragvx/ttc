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

from packages.ledger.deltas import ConnectionOp, CouplingOp, FeatureOp, FitOp, InstanceOp, JoinAnnotationOp, ParameterDelta, RegionOp, is_forbidden_target
from packages.ledger.parameter import LockState, ParameterDef, ParamSource
from packages.ledger.schema import (
    Connection,
    Coupling,
    CouplingInput,
    CutFeature,
    FitBinding,
    FitInput,
    Instance,
    InterfaceRef,
    JoinAnnotation,
    MasterParametricLedger,
    Region,
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
    # 2026-08-01 (scoped MVP — a single passthrough tag): the triggering ParameterDelta's own
    # `source` (packages/ledger/deltas.py), threaded through here so it survives the apply_delta/
    # _apply_string_delta call rather than being silently dropped — purely descriptive, for later
    # display; never read by any validation/acceptance logic in this module. Defaults to "unsourced"
    # exactly like ParameterDelta.source, so every pre-existing outcome/test keeps behaving as today.
    source: ParamSource = "unsourced"

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

    def _outcome(*args, **kwargs) -> ApplyOutcome:
        """Local factory so every ApplyOutcome this function returns carries `delta.source` without
        repeating it at each of the many early-return call sites below (see ApplyOutcome.source's own
        docstring for why this must never be silently dropped)."""
        kwargs.setdefault("source", delta.source)
        return ApplyOutcome(*args, **kwargs)

    target = delta.target_node
    requested = delta.requested_value
    if not isinstance(requested, str):
        return ledger, _outcome(
            ApplyStatus.REJECTED, target, old_value=current,
            message=f"{target} is a string-valued node — requested_value must be a string, not {requested!r}")
    if delta.set_lock is not None:
        return ledger, _outcome(ApplyStatus.REJECTED, target, old_value=current,
                                message="cannot set_lock on a string-valued node")
    if requested not in MATERIAL_DB:
        return ledger, _outcome(
            ApplyStatus.REJECTED, target, old_value=current,
            message=f"unknown material {requested!r} (known: {sorted(MATERIAL_DB)})")

    new_ledger = ledger.model_copy(deep=True)
    n_parent, n_attr, _ = _resolve(new_ledger, target)
    _set(n_parent, n_attr, requested)

    violations = check_invariants(new_ledger, domain_checks)
    if violations:
        return ledger, _outcome(ApplyStatus.CONFLICT, target, old_value=current,
                                new_value=requested, message="; ".join(violations))
    return new_ledger, _outcome(ApplyStatus.APPLIED, target, old_value=current, new_value=requested)


def apply_delta(
    ledger: MasterParametricLedger,
    delta: ParameterDelta,
    domain_checks: Optional[Callable[[MasterParametricLedger], list[str]]] = None,
    cascade_rules: Optional[CascadeRule] = None,
) -> tuple[MasterParametricLedger, ApplyOutcome]:
    def _outcome(*args, **kwargs) -> ApplyOutcome:
        """Local factory so every ApplyOutcome this function returns carries `delta.source` without
        repeating it at each of the many early-return call sites below (see ApplyOutcome.source's own
        docstring for why this must never be silently dropped)."""
        kwargs.setdefault("source", delta.source)
        return ApplyOutcome(*args, **kwargs)

    target = delta.target_node
    if is_forbidden_target(target):
        return ledger, _outcome(ApplyStatus.REJECTED, target, message="LLM may not write derived/review nodes")

    parent, attr, current = _resolve(ledger, target)
    if parent is None:
        return ledger, _outcome(ApplyStatus.REJECTED, target, message="unknown or non-tunable node")

    if isinstance(current, str):
        return _apply_string_delta(ledger, delta, parent, attr, current, domain_checks)

    if not isinstance(current, ParameterDef):
        return ledger, _outcome(ApplyStatus.REJECTED, target, message="unknown or non-tunable node")

    if current.is_locked:
        return ledger, _outcome(ApplyStatus.REJECTED, target, old_value=current.value,
                                message="HARD_LOCK parameter is frozen")

    requested = delta.requested_value
    if not isinstance(requested, (int, float)):
        return ledger, _outcome(ApplyStatus.REJECTED, target, old_value=current.value,
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
        return ledger, _outcome(ApplyStatus.CONFLICT, target, old_value=current.value,
                                new_value=requested, message="; ".join(violations))

    if outside_recommended:
        msg = f"{requested} is outside recommended range [{lo}, {hi}] — applied on copilot judgment"
        return new_ledger, _outcome(ApplyStatus.APPLIED_ADVISORY, target,
                                    old_value=current.value, new_value=requested, message=msg,
                                    cascades=cascade_effects)
    return new_ledger, _outcome(ApplyStatus.APPLIED, target,
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
        # neither endpoint's (instance, interface) may already be claimed by a DIFFERENT existing
        # connection: resolve_placements (packages/subsystems/placement.py) positions each mated
        # neighbor from its host's interface FRAME, so two connections sharing one host interface
        # silently place both neighbors at the identical world Transform (2026-07-21 audit, HIGH) —
        # and connection_issues() can't catch it after the fact because each connection's own two
        # endpoints DO coincide (that's the whole bug). Checked against the CURRENT live connection
        # set (not history), so removing a connection frees its interface for a new one; a same-id
        # re-add of the identical connection can't reach here — the id-uniqueness check above already
        # REJECTED it (this codebase has no "update an existing connection" op).
        claimed_by = next(
            (c for c in ledger.connections
             if (c.a.instance_id, c.a.interface) == (iid, iface)
             or (c.b.instance_id, c.b.interface) == (iid, iface)),
            None,
        )
        if claimed_by is not None:
            return ledger, ConnectionOpOutcome(
                ApplyStatus.REJECTED, op.id,
                message=f"endpoint {side}: {iid}.{iface} is already connected via {claimed_by.id!r} "
                        f"({claimed_by.a.instance_id}.{claimed_by.a.interface} <-> "
                        f"{claimed_by.b.instance_id}.{claimed_by.b.interface})")

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


@dataclass
class FitOpOutcome:
    """FitOp's analog of CouplingOpOutcome. Carries the resolved FitBinding (wired/unwired) plus the
    ParameterDeltas actually applied for each dimension the fit wrote — the caller (packages/transport/
    app.py) logs these via `EventLog.append_fit_bound`/`append_fit_resynced` so replay can re-apply
    them exactly (mirrors how PARAMETER_MUTATION's own replay re-runs apply_delta)."""

    status: ApplyStatus
    fit_id: Optional[str]
    binding: Optional[FitBinding] = None
    deltas: list[ParameterDelta] = field(default_factory=list)
    delta_outcomes: list[ApplyOutcome] = field(default_factory=list)
    message: str = ""

    @property
    def changed(self) -> bool:
        return self.status in (ApplyStatus.APPLIED, ApplyStatus.APPLIED_ADVISORY)


def _next_fit_id(ledger: MasterParametricLedger) -> str:
    existing = {f.id for f in ledger.fit_bindings}
    n = 1
    while f"fit_{n}" in existing:
        n += 1
    return f"fit_{n}"


# Rough, honest placeholder clearances by join method (mm) -- NOT a handbook tolerance value, a
# neutral starting point when the caller didn't state one AND a JoinAnnotation gives SOME signal
# about intent. Per CLAUDE.md's human-wall list, a REAL manufacturing-tolerance number (material/
# process-dependent) needs an engineer's sign-off before being treated as authoritative -- this only
# exists so an omitted clearance isn't silently wrong-signed (a press-fit defaulting to a clearance
# gap would be backwards), not to fabricate precision this system doesn't have.
_DEFAULT_CLEARANCE_BY_METHOD_MM: dict[str, float] = {
    "press_fit": -0.1, "bolted": 0.3, "welded": 0.0, "adhesive": 0.1, "custom": 0.0,
}


def _default_clearance_from_join_annotation(ledger: MasterParametricLedger, connector_id: str, host_id: str) -> float:
    """When `fit_connector` omits `clearance_mm`, check whether a JoinAnnotation already exists on a
    Connection between these exact two instances (either direction) and use its `method` to pick a
    sign-appropriate placeholder default (see `_DEFAULT_CLEARANCE_BY_METHOD_MM` above). Falls back to
    0.0 (a neutral nominal fit, unchanged from the pre-JoinAnnotation default) when no connection or
    no annotation exists — this NEVER blocks `fit_connector`, it only tries to pick a better-than-
    nothing default when real signal is available. `JoinAnnotation.method` is read here, never
    written — `FitBinding` never stores its own copy of it (see FitBinding's own docstring)."""
    conn_id = next((c.id for c in ledger.connections
                    if {c.a.instance_id, c.b.instance_id} == {connector_id, host_id}), None)
    if conn_id is None:
        return 0.0
    annotation = next((j for j in ledger.join_annotations if j.connection_id == conn_id), None)
    if annotation is None:
        return 0.0
    return _DEFAULT_CLEARANCE_BY_METHOD_MM.get(annotation.method, 0.0)


def apply_fit_op(
    ledger: MasterParametricLedger,
    op: FitOp,
    compute_fit: Callable[[MasterParametricLedger, str, str, float], "object"],
    is_managed_child: Callable[[MasterParametricLedger, str], bool],
    check_invariants: Callable[[MasterParametricLedger, str], list[str]],
) -> tuple[MasterParametricLedger, FitOpOutcome]:
    """Apply one FitOp (wire/unwire/resync a typed fit binding). Returns a NEW ledger + outcome;
    original never mutated (same event-sourcing convention as apply_coupling_op).

    This package stays registry-free (`packages/ledger/CLAUDE.md`) — `compute_fit` (the actual
    cross-section arithmetic, living in `packages.subsystems.fit`), `is_managed_child` (whether an
    instance is an assembly_template-generated child whose params get silently overwritten every
    reconcile pass), and `check_invariants(ledger, instance_id)` (that instance's own subsystem-level
    invariants — e.g. spar_joiner_sleeve's own "bore >= outer diameter, no wall left" check) are
    injected, mirroring `apply_coupling_op`'s `known_relations`/`inputs_of` injection exactly — this
    function never imports `packages.subsystems`. `check_invariants` mirrors the SAME
    `_s.check_invariants(ledger, _t)` lambda `SessionState.mutate()` (packages/transport/app.py)
    already builds for an ordinary hand-typed delta — a fit-derived delta must be checked exactly the
    same way, not exempted from invariants just because it was computed rather than typed.

    `compute_fit(ledger, connector_id, host_id, clearance_mm)` returns an object with `.ok: bool`,
    `.kind: Optional[str]`, `.values: dict[str, float]` (connector_param -> computed value),
    `.dim_map: dict[str, str]` (host_param -> connector_param, recorded on the FitBinding for later
    drift-checking), `.reason: Optional[str]` (set when `.ok` is False).

    Every dimension a fit computes is written through the SAME `apply_delta` path any hand-typed
    ParameterDelta uses — including its bounds policy: `packages/ledger/CLAUDE.md`'s "bounds are
    ADVISORY, not a hard construction-time clamp" is a deliberate, system-wide, uniform rule (a user
    asking for 14 legs on a table gets 14, not silently clamped to 12) and a fit-derived value is not
    a special case that overrides it — a fit whose computed dimension falls outside the connector's
    recommended range still applies, as APPLIED_ADVISORY, exactly like a hand-typed one would. Only a
    HARD_LOCK or a genuine cross-field invariant violation (REJECTED/CONFLICT) backs the WHOLE fit out
    atomically — none of the dimensions are applied and no FitBinding is recorded, so a connector never
    ends up half-fitted."""
    if op.op == "unfit_connector":
        if not op.id:
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, None, message="unfit_connector requires id")
        match = next((f for f in ledger.fit_bindings if f.id == op.id), None)
        if match is None:
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, op.id, message=f"unknown fit id {op.id!r}")
        new = ledger.model_copy(update={"fit_bindings": [f for f in ledger.fit_bindings if f.id != op.id]})
        return new, FitOpOutcome(
            ApplyStatus.APPLIED, op.id, binding=match,
            message=f"unwired fit {op.id} — the connector KEEPS its last-fitted dimensions (unfitting "
                    f"doesn't revert geometry, same as removing a coupling doesn't un-derive a load)")

    if op.op not in ("fit_connector", "resync_fit"):
        return ledger, FitOpOutcome(ApplyStatus.REJECTED, op.id, message=f"unknown op {op.op!r}")

    if op.op == "resync_fit":
        if not op.id:
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, None, message="resync_fit requires id")
        existing = next((f for f in ledger.fit_bindings if f.id == op.id), None)
        if existing is None:
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, op.id, message=f"unknown fit id {op.id!r}")
        connector_id = existing.connector_instance
        host_id = existing.host_instance
        clearance = existing.clearance_mm
        fit_id = op.id
    else:
        missing = [f for f in ("connector_instance", "host_instance") if getattr(op, f) is None]
        if missing:
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, op.id,
                                        message=f"fit_connector requires {', '.join(missing)}")
        if op.connector_instance not in ledger.instances:
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, op.id,
                                        message=f"unknown instance {op.connector_instance!r}")
        if op.host_instance not in ledger.instances:
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, op.id,
                                        message=f"unknown instance {op.host_instance!r}")
        if op.connector_instance == op.host_instance:
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, op.id,
                                        message="a connector cannot be fitted to itself")
        if op.id is not None and any(f.id == op.id for f in ledger.fit_bindings):
            return ledger, FitOpOutcome(ApplyStatus.REJECTED, op.id, message=f"fit id {op.id!r} already exists")
        if any(f.connector_instance == op.connector_instance for f in ledger.fit_bindings):
            return ledger, FitOpOutcome(
                ApplyStatus.REJECTED, op.id,
                message=f"{op.connector_instance!r} already has a live fit binding — unfit it first, or "
                        f"use resync_fit if the host's dimensions just changed (v1: one fit per connector)")
        if is_managed_child(ledger, op.connector_instance):
            return ledger, FitOpOutcome(
                ApplyStatus.REJECTED, op.id,
                message=f"{op.connector_instance!r} is a managed assembly-template child — its params "
                        f"are overwritten every reconcile pass, so a direct fit would be silently "
                        f"discarded on the next read. Route the shared dimension through the master's "
                        f"own params instead (the same way table.py's leg_dia_mm already reaches every leg).")
        connector_id = op.connector_instance
        host_id = op.host_instance
        clearance = (op.clearance_mm if op.clearance_mm is not None
                    else _default_clearance_from_join_annotation(ledger, connector_id, host_id))
        fit_id = op.id if op.id is not None else _next_fit_id(ledger)

    result = compute_fit(ledger, connector_id, host_id, clearance)
    if not result.ok:
        return ledger, FitOpOutcome(ApplyStatus.REJECTED, fit_id, message=result.reason or "fit could not be computed")

    working = ledger
    deltas: list[ParameterDelta] = []
    delta_outcomes: list[ApplyOutcome] = []
    domain_checks = lambda led: check_invariants(led, connector_id)  # noqa: E731
    for connector_param, value in result.values.items():
        d = ParameterDelta(target_node=f"instances.{connector_id}.params.{connector_param}",
                           requested_value=value, rationale=op.rationale or f"fitted from {host_id}")
        working, outcome = apply_delta(working, d, domain_checks=domain_checks)
        deltas.append(d)
        delta_outcomes.append(outcome)
        if outcome.status in (ApplyStatus.REJECTED, ApplyStatus.CONFLICT):
            return ledger, FitOpOutcome(
                ApplyStatus.REJECTED, fit_id, delta_outcomes=delta_outcomes,
                message=f"{connector_param}: {outcome.message} — the fit was NOT applied (all-or-"
                        f"nothing; {connector_id}'s params are unchanged)")

    if op.op == "resync_fit":
        return working, FitOpOutcome(ApplyStatus.APPLIED, fit_id, binding=existing, deltas=deltas,
                                     delta_outcomes=delta_outcomes,
                                     message=f"resynced fit {fit_id} against {host_id}'s current dimensions")

    binding = FitBinding(
        id=fit_id, connector_instance=connector_id, host_instance=host_id, kind=result.kind,
        inputs=[FitInput(host_param=hp, connector_param=cp) for hp, cp in result.dim_map.items()],
        clearance_mm=clearance,
    )
    working = working.model_copy(update={"fit_bindings": [*working.fit_bindings, binding]})
    return working, FitOpOutcome(ApplyStatus.APPLIED, fit_id, binding=binding, deltas=deltas,
                                 delta_outcomes=delta_outcomes, message=f"fitted {connector_id} <- {host_id}")


@dataclass
class JoinAnnotationOpOutcome:
    """JoinAnnotationOp's analog of CouplingOpOutcome. Carries the resolved JoinAnnotation (added or
    removed)."""

    status: ApplyStatus
    join_id: Optional[str]
    annotation: Optional[JoinAnnotation] = None
    message: str = ""

    @property
    def changed(self) -> bool:
        return self.status is ApplyStatus.APPLIED


def _next_join_id(ledger: MasterParametricLedger) -> str:
    existing = {j.id for j in ledger.join_annotations}
    n = 1
    while f"join_{n}" in existing:
        n += 1
    return f"join_{n}"


def apply_join_annotation_op(
    ledger: MasterParametricLedger, op: JoinAnnotationOp,
) -> tuple[MasterParametricLedger, JoinAnnotationOpOutcome]:
    """Apply one JoinAnnotationOp (add/remove semantic HOW-joined data on an existing Connection).
    Returns a NEW ledger + outcome; original never mutated (same event-sourcing convention as
    apply_coupling_op). No injected callables needed — unlike CouplingOp/FitOp, this never touches the
    subsystem registry or a part's own params; `connection_id` is checked against `ledger.connections`
    directly, already in scope in this registry-free package."""
    if op.op == "remove_join_annotation":
        if not op.id:
            return ledger, JoinAnnotationOpOutcome(ApplyStatus.REJECTED, None,
                                                   message="remove_join_annotation requires id")
        match = next((j for j in ledger.join_annotations if j.id == op.id), None)
        if match is None:
            return ledger, JoinAnnotationOpOutcome(ApplyStatus.REJECTED, op.id,
                                                   message=f"unknown join annotation id {op.id!r}")
        new = ledger.model_copy(update={
            "join_annotations": [j for j in ledger.join_annotations if j.id != op.id]})
        return new, JoinAnnotationOpOutcome(ApplyStatus.APPLIED, op.id, annotation=match,
                                            message=f"removed join annotation {op.id}")

    if op.op != "add_join_annotation":
        return ledger, JoinAnnotationOpOutcome(ApplyStatus.REJECTED, op.id, message=f"unknown op {op.op!r}")

    missing = [f for f in ("connection_id", "method") if getattr(op, f) is None]
    if missing:
        return ledger, JoinAnnotationOpOutcome(ApplyStatus.REJECTED, op.id,
                                               message=f"add_join_annotation requires {', '.join(missing)}")
    if not any(c.id == op.connection_id for c in ledger.connections):
        return ledger, JoinAnnotationOpOutcome(
            ApplyStatus.REJECTED, op.id,
            message=f"unknown connection {op.connection_id!r} — the two parts must already be "
                    f"connection_ops-mated before annotating HOW they're joined")
    if op.id is not None and any(j.id == op.id for j in ledger.join_annotations):
        return ledger, JoinAnnotationOpOutcome(ApplyStatus.REJECTED, op.id,
                                               message=f"join annotation id {op.id!r} already exists")
    if any(j.connection_id == op.connection_id for j in ledger.join_annotations):
        return ledger, JoinAnnotationOpOutcome(
            ApplyStatus.REJECTED, op.id,
            message=f"connection {op.connection_id!r} already has a join annotation — remove it "
                    f"first if you want to change the method (v1: one annotation per connection)")

    join_id = op.id if op.id is not None else _next_join_id(ledger)
    annotation = JoinAnnotation(id=join_id, connection_id=op.connection_id, method=op.method,
                                fastener=op.fastener, note=op.note)
    new_ledger = ledger.model_copy(update={"join_annotations": [*ledger.join_annotations, annotation]})
    return new_ledger, JoinAnnotationOpOutcome(ApplyStatus.APPLIED, join_id, annotation=annotation,
                                               message=f"annotated connection {op.connection_id} as {op.method}")


@dataclass
class RegionOpOutcome:
    """RegionOp's analog of ConnectionOpOutcome. Carries the resolved Region (added or removed)."""

    status: ApplyStatus
    region_id: Optional[str]
    region: Optional[Region] = None
    message: str = ""

    @property
    def changed(self) -> bool:
        return self.status is ApplyStatus.APPLIED


def _next_region_id(ledger: MasterParametricLedger) -> str:
    existing = {r.id for r in ledger.regions}
    n = 1
    while f"region_{n}" in existing:
        n += 1
    return f"region_{n}"


def apply_region_op(
    ledger: MasterParametricLedger,
    op: RegionOp,
) -> tuple[MasterParametricLedger, RegionOpOutcome]:
    """Apply one RegionOp (add/remove a typed keep-out/keep-in box on a HOST instance). Returns a NEW
    ledger + outcome; original never mutated (same event-sourcing convention as apply_connection_op).

    No injected callables needed — unlike ConnectionOp (interfaces_of) / CouplingOp (known_relations,
    inputs_of) / FitOp (compute_fit, is_managed_child, check_invariants), a Region is a pure geometric
    ANNOTATION: it never touches the subsystem registry or a part's own params. `host_instance` is
    checked against `ledger.instances` directly, already in scope in this registry-free package."""
    if op.op == "remove_region":
        if not op.id:
            return ledger, RegionOpOutcome(ApplyStatus.REJECTED, None, message="remove_region requires id")
        match = next((r for r in ledger.regions if r.id == op.id), None)
        if match is None:
            return ledger, RegionOpOutcome(ApplyStatus.REJECTED, op.id, message=f"unknown region id {op.id!r}")
        new = ledger.model_copy(update={"regions": [r for r in ledger.regions if r.id != op.id]})
        return new, RegionOpOutcome(ApplyStatus.APPLIED, op.id, region=match, message=f"removed region {op.id}")

    if op.op != "add_region":
        return ledger, RegionOpOutcome(ApplyStatus.REJECTED, op.id, message=f"unknown op {op.op!r}")

    # add_region: all nine fields required
    missing = [f for f in ("host_instance", "kind", "label", "x_mm", "y_mm", "z_mm", "dx_mm", "dy_mm", "dz_mm")
               if getattr(op, f) is None]
    if missing:
        return ledger, RegionOpOutcome(ApplyStatus.REJECTED, op.id,
                                       message=f"add_region requires {', '.join(missing)}")
    if op.id is not None and any(r.id == op.id for r in ledger.regions):
        return ledger, RegionOpOutcome(ApplyStatus.REJECTED, op.id, message=f"region id {op.id!r} already exists")
    if op.host_instance not in ledger.instances:
        return ledger, RegionOpOutcome(ApplyStatus.REJECTED, op.id,
                                       message=f"unknown instance {op.host_instance!r}")
    # box extents must be strictly positive -- REJECT, never silently clamp (same physical-sanity floor
    # as CutFeature's dia_mm/length_mm/width_mm > 0 check, schema.py::CutFeature._check_shape_fields).
    # Checked explicitly here (rather than only relying on Region's own Field(gt=0.0)) for a clean
    # REJECTED message that names every offending field, mirroring ConnectionOp/CouplingOp's own
    # explicit-field-check style rather than surfacing a raw ValidationError string.
    bad_dims = [(name, v) for name, v in (("dx_mm", op.dx_mm), ("dy_mm", op.dy_mm), ("dz_mm", op.dz_mm))
                if v <= 0.0]
    if bad_dims:
        clauses = ", ".join(f"{name}={v}" for name, v in bad_dims)
        return ledger, RegionOpOutcome(ApplyStatus.REJECTED, op.id,
                                       message=f"region extents must be > 0 (got {clauses})")

    region_id = op.id if op.id is not None else _next_region_id(ledger)
    try:
        region = Region(id=region_id, host_instance=op.host_instance, kind=op.kind, label=op.label,
                        x_mm=op.x_mm, y_mm=op.y_mm, z_mm=op.z_mm,
                        dx_mm=op.dx_mm, dy_mm=op.dy_mm, dz_mm=op.dz_mm)
    except Exception as exc:  # belt-and-suspenders — the explicit checks above should already catch
                               # every REJECT-worthy case, but a schema-level validator must never crash
                               # this function if it ever disagrees (mirrors apply_feature_op's own
                               # try/except around CutFeature construction).
        return ledger, RegionOpOutcome(ApplyStatus.REJECTED, op.id, message=str(exc))

    new_ledger = ledger.model_copy(update={"regions": [*ledger.regions, region]})
    return new_ledger, RegionOpOutcome(ApplyStatus.APPLIED, region_id, region=region,
                                       message=f"added region {region_id} ({op.kind}) on {op.host_instance}")
