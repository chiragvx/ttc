"""Subsystem registry — the physical-assembly axis (bracket, enclosure, standoff, … → wing, fuselage).

Orthogonal to the discipline axis (packages/disciplines/): a subsystem is a *part/assembly* with a
geometry generator; multiple disciplines analyze it (the disciplines × subsystems matrix in
build-plan/reference/DOMAIN_TAXONOMY.md). Each subsystem self-describes: its LLM knowledge fragment,
which disciplines apply, which params drive its geometry, and a (lazy) geometry builder.

Adding a subsystem: create packages/subsystems/<name>.py, build a SubsystemContext, call register().
The prompt builder + geometry endpoints pull from here — no other file changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

# NEW-STYLE (Phase A) — the scalable model. Existing subsystems keep using SubsystemContext below
# until they migrate. Both APIs coexist during the transition.
from packages.subsystems.base import (
    Namespace,
    ParamSpec,
    Subsystem,
    geometry_paths,
    resolve_namespace,
    seed_instance,
    seed_ledger_geometry,
)
# Phase F (2026-07-03) — composition helpers. A subsystem's `build` invokes another registered
# subsystem's `build` with overrides + positions the result. See packages/subsystems/compose.py.
# Re-exported from the package so a composite subsystem file just imports from `packages.subsystems`.

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger


def _no_invariants(ledger: "MasterParametricLedger") -> list[str]:
    return []


def _identity(ledger: "MasterParametricLedger") -> "MasterParametricLedger":
    return ledger


@dataclass(frozen=True)
class SubsystemContext:
    """Self-describing physical part/assembly: knowledge, applicable disciplines, geometry hooks."""

    name: str
    description: str
    prompt_fragment: str
    # which discipline lenses apply to this subsystem (keys into packages/disciplines)
    applicable_disciplines: tuple[str, ...] = ()
    # params (dotted ledger paths) that drive THIS subsystem's geometry AT THE ROOT INSTANCE. For an
    # arbitrary (possibly non-root) instance, use `packages.subsystems.base.geometry_paths(model, id)`.
    geometry_params: tuple[str, ...] = ()
    # subsystem-specific cross-field invariants (beyond the general ones in apply.py). Optional 2nd
    # arg `instance_id` (default None -> ledger.root_id) targets a non-root instance (Item 3 outliner).
    check_invariants: Callable[..., list[str]] = field(default=_no_invariants)
    # ledger [, instance_id] -> TaggedPart. Kept optional + resolved lazily so importing this package
    # never pulls in build123d/OCCT (the pure-python layers must not depend on the kernel).
    geometry_builder: Optional[Callable[..., object]] = None
    # ledger [, instance_id] -> printed-material volume in mm³ (drives mass/print-time telemetry).
    volume_mm3: Optional[Callable[..., float]] = None
    # populate this subsystem's optional geometry block with sensible defaults on a fresh project
    # (identity for subsystems that live entirely in the required core, e.g. bracket).
    seed_defaults: Callable[["MasterParametricLedger"], "MasterParametricLedger"] = field(default=_identity)
    # 2026-07-03 — see Subsystem.fea_eligible: True only for parts sharing the validated cantilever
    # FS methodology. False (default) -> factor_of_safety honestly stays "unknown" for this part type.
    fea_eligible: bool = False
    # 2026-07-03 — see Subsystem.cascades: an optional packages.ledger.apply.CascadeRule this part
    # declares (e.g. bracket's edge-distance rule cascades plate_depth_mm). None = no cascades.
    cascades: Optional[Callable[..., list]] = None


SUBSYSTEM_REGISTRY: dict[str, SubsystemContext] = {}
# Phase F: parallel model registry — keeps the `Subsystem` dataclass reachable by name so the
# `call(name, **overrides)` compose helper can materialise a child's ParamSpec defaults, apply
# overrides, and invoke the child's build. SubsystemContext (the ledger-facing adapter) doesn't
# carry `params`/`build` on the same shape, so we index the raw model alongside.
SUBSYSTEM_MODELS: dict[str, Subsystem] = {}


def register(ctx: SubsystemContext) -> SubsystemContext:
    SUBSYSTEM_REGISTRY[ctx.name] = ctx
    return ctx


def get_subsystem(name: str) -> SubsystemContext:
    if name not in SUBSYSTEM_REGISTRY:
        raise KeyError(f"Unknown subsystem {name!r}. Available: {sorted(SUBSYSTEM_REGISTRY)}")
    return SUBSYSTEM_REGISTRY[name]


def get_subsystem_model(name: str) -> Subsystem:
    """Fetch the raw `Subsystem` (params + build hooks) — used by the Phase F compose helpers to
    invoke a child subsystem's build with overrides. Prefer `get_subsystem()` when you need the
    ledger-facing SubsystemContext instead."""
    if name not in SUBSYSTEM_MODELS:
        raise KeyError(f"Unknown subsystem {name!r}. Available: {sorted(SUBSYSTEM_MODELS)}")
    return SUBSYSTEM_MODELS[name]


def register_subsystem(sub: Subsystem) -> Subsystem:
    """Register a new-style Subsystem. An adapter presents it as a SubsystemContext so the rest of the
    code (telemetry, prompt builder, /params, /mesh, /export/step) works UNCHANGED. Phase E removes the
    adapter and switches consumers to native Subsystem accessors.

    `_check`/`_build`/`_volume` all accept an optional trailing `instance_id` (default None ->
    `ledger.root_id`) so the SAME registered subsystem can be resolved against ANY instance in the
    tree — the foundation the Item 3 outliner (multiple independently-editable instances) builds on.
    Every pre-existing call site that passes just `ledger` is unaffected."""
    from packages.subsystems.base import geometry_paths as _geometry_paths
    from packages.subsystems.base import resolve_namespace, seed_ledger_geometry
    from packages.subsystems.cut_features import apply_cut_features, swept_volume_mm3

    root_geometry_paths = _geometry_paths(sub, "root")

    def _check(ledger, instance_id=None):
        return sub.invariants(resolve_namespace(sub, ledger, instance_id))

    def _build(ledger, instance_id=None):
        result = sub.build(resolve_namespace(sub, ledger, instance_id)) if sub.build else None
        if result is None:
            return None
        inst = ledger.instances.get(instance_id or ledger.root_id)
        if inst is not None and inst.cut_features:
            result = apply_cut_features(result, inst.cut_features)
        return result

    def _volume(ledger, instance_id=None):
        vol = sub.volume(resolve_namespace(sub, ledger, instance_id)) if sub.volume else 0.0
        inst = ledger.instances.get(instance_id or ledger.root_id)
        if inst is not None and inst.cut_features:
            vol = max(0.0, vol - sum(swept_volume_mm3(f) for f in inst.cut_features))
        return vol

    def _seed(ledger):
        return seed_ledger_geometry(sub, ledger)

    SUBSYSTEM_REGISTRY[sub.name] = SubsystemContext(
        name=sub.name,
        description=sub.description,
        prompt_fragment=sub.fragment,
        applicable_disciplines=sub.disciplines,
        geometry_params=root_geometry_paths,
        check_invariants=_check,
        geometry_builder=_build,
        volume_mm3=_volume,
        seed_defaults=_seed,
        fea_eligible=sub.fea_eligible,
        cascades=sub.cascades,
    )
    SUBSYSTEM_MODELS[sub.name] = sub
    return sub


def add_instance(ledger: "MasterParametricLedger", subsystem_name: str, instance_id: str,
                 parent_id: Optional[str] = None) -> "MasterParametricLedger":
    """Add a NEW instance (of any registered subsystem type) to the ledger's instance tree, seeded
    with that subsystem's defaults. Parts are a FLAT set brought into a file (2026-07-04) — no
    root, no auto-parenting: `parent_id` omitted means top-level; an unknown `parent_id` silently
    falls back to top-level rather than rejecting the add (see
    `packages.ledger.apply.resolve_instance_parent`). Raises KeyError for an unknown subsystem
    name; raises ValueError if `instance_id` is already taken. Item 3 outliner CRUD builds on
    this."""
    from packages.ledger.apply import resolve_instance_parent
    if instance_id in ledger.instances:
        raise ValueError(f"instance id {instance_id!r} already exists")
    pid, _parent_note = resolve_instance_parent(ledger, parent_id)
    model = get_subsystem_model(subsystem_name)  # KeyError if unknown — validated before mutating
    inst = seed_instance(model, instance_id, parent_id=pid)
    new_instances = dict(ledger.instances)
    new_instances[instance_id] = inst
    new_ledger = ledger.model_copy(update={"instances": new_instances})
    # Assembly-template mechanism (2026-07-03): a safe no-op unless `subsystem_name` declares
    # `assembly_children` — in that case this materializes the new instance's own child instances too.
    from packages.subsystems.assembly_template import reconcile_children
    return reconcile_children(new_ledger, instance_id)


def remove_instance(ledger: "MasterParametricLedger", instance_id: str) -> "MasterParametricLedger":
    """Remove a childless instance — any part in the file is removable as long as nothing depends
    on it (2026-07-04: parts are a flat set, there's no root carve-out). Raises ValueError for an
    unknown id or an instance that still has children (delete children first — no silent cascade);
    that check alone already prevents orphaning a template's or explicitly-parented instance's
    dependents."""
    if instance_id not in ledger.instances:
        raise ValueError(f"instance id {instance_id!r} does not exist")
    children = [i for i, inst in ledger.instances.items() if inst.parent_id == instance_id]
    if children:
        raise ValueError(f"instance {instance_id!r} has children {children} — remove them first")
    new_instances = dict(ledger.instances)
    del new_instances[instance_id]
    return ledger.model_copy(update={"instances": new_instances})


# Phase F composition helpers — re-exported for composite subsystems' build functions.
from packages.subsystems.compose import call, compose, fuse, place, place_polar  # noqa: E402


# Side-effect imports: each module calls register() on load.
from packages.subsystems import bracket as _bracket  # noqa: E402, F401
from packages.subsystems import enclosure as _enclosure  # noqa: E402, F401
from packages.subsystems import standoff as _standoff  # noqa: E402, F401
from packages.subsystems import lbracket as _lbracket  # noqa: E402, F401
from packages.subsystems import uchannel as _uchannel  # noqa: E402, F401
from packages.subsystems import panel as _panel  # noqa: E402, F401
from packages.subsystems import washer as _washer  # noqa: E402, F401
from packages.subsystems import round_post as _round_post  # noqa: E402, F401 — solid cylinder primitive (used by table legs)
from packages.subsystems import table as _table  # noqa: E402, F401 — composite: flat_bar top + round_post legs
# Phase 1 catalog expansion (2026-07-02) — 15 new subsystems across categories
from packages.subsystems import flat_bar as _flat_bar  # noqa: E402, F401
from packages.subsystems import square_tube as _square_tube  # noqa: E402, F401
from packages.subsystems import dowel_pin as _dowel_pin  # noqa: E402, F401
from packages.subsystems import cover_plate as _cover_plate  # noqa: E402, F401
from packages.subsystems import t_bar as _t_bar  # noqa: E402, F401
from packages.subsystems import z_bracket as _z_bracket  # noqa: E402, F401
from packages.subsystems import mounting_plate_grid as _mounting_plate_grid  # noqa: E402, F401
from packages.subsystems import shaft_collar as _shaft_collar  # noqa: E402, F401
from packages.subsystems import hub as _hub  # noqa: E402, F401
from packages.subsystems import threaded_boss as _threaded_boss  # noqa: E402, F401
from packages.subsystems import motor_mount as _motor_mount  # noqa: E402, F401
from packages.subsystems import hex_nut as _hex_nut  # noqa: E402, F401
from packages.subsystems import hex_bar as _hex_bar  # noqa: E402, F401
from packages.subsystems import hex_standoff as _hex_standoff  # noqa: E402, F401
# Phase F composite — plate + N standoffs, first composite-of-registered-parts (2026-07-03)
from packages.subsystems import standoff_frame as _standoff_frame  # noqa: E402, F401
# Open semi-circular saddle/P-clamp — cradles a cylindrical item (fan housing, pipe, tube) (2026-07-03)
from packages.subsystems import saddle_clamp as _saddle_clamp  # noqa: E402, F401
# Aerospace airframe structural members (2026-07-05)
from packages.subsystems import bulkhead_frame as _bulkhead_frame  # noqa: E402, F401
from packages.subsystems import longeron as _longeron  # noqa: E402, F401
# General body-of-revolution primitive (loft + hollow shell) — not aerospace-specific (2026-07-05)
from packages.subsystems import lofted_spindle as _lofted_spindle  # noqa: E402, F401
# Asymmetric top/bottom hull + localized canopy bump — lofted_spindle's asymmetric sibling (2026-07-05)
from packages.subsystems import lofted_hull as _lofted_hull  # noqa: E402, F401
# Full-span lofted wing panel, real NACA 4-digit symmetric airfoil cross-section (2026-07-05)
from packages.subsystems import naca_wing as _naca_wing  # noqa: E402, F401
# Streamlined body-of-revolution for fuselages/nose cones/nacelles — power-law (ogive) nose/tail
# taper, lofted_spindle's aerospace-shaped sibling (2026-07-06)
from packages.subsystems import ogive_fuselage as _ogive_fuselage  # noqa: E402, F401
# Composite: ogive_fuselage body + naca_wing panel, boolean-fused into one printable body (2026-07-05)
from packages.subsystems import winged_fuselage as _winged_fuselage  # noqa: E402, F401
