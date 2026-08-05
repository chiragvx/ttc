"""Assembly-template mechanism (2026-07-03) — turn a "master" Subsystem's params into REAL sibling
`Instance`s in the ledger's instance tree, instead of fused geometry.

A `Subsystem` normally owns its own `build` and produces one solid. An assembly-template Subsystem
instead sets `Subsystem.assembly_children` (and leaves `build=None`) — a callable that reads the
master instance's resolved params and returns the list of `ChildSpec`s it WANTS to exist as children.
`reconcile_children()` is the pure-Python diff/apply step: given a root instance id, it resolves the
desired child list, and reconciles it against whatever children currently exist under that root
(update existing, create missing, remove stale) — so calling it again after a master param change
(e.g. a leg count) converges the tree to the new desired shape without duplicating instances.

NESTED assembly-templates (2026-08-04): a child an assembly-template instance materializes can
itself be an assembly-template instance (its own subsystem_type also declares `assembly_children`)
— `reconcile_children()` recurses into that child's own children automatically, to any depth, with an
explicit ancestor-chain guard that rejects (rather than infinitely recurses on) a subsystem type that
would directly or transitively contain itself. See `reconcile_children()`'s own docstring.

Pure composition only, matching this package's convention (`compose.py`, `assembly.py`): no build123d
import at module scope, so importing this module never drags in the kernel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from packages.ledger.parameter import ParameterDef
from packages.subsystems.base import resolve_namespace

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger


def reconcile_children(
    ledger: "MasterParametricLedger",
    root_instance_id: str,
    _ancestor_types: tuple[str, ...] = (),
) -> "MasterParametricLedger":
    """Reconcile `root_instance_id`'s children against its subsystem's `assembly_children` (if any).

    Safe no-op for a non-assembly-template instance (`assembly_children is None`) — every call site
    can call this unconditionally without checking first. Otherwise: resolves the master namespace,
    calls `assembly_children(ns)` for the desired `list[ChildSpec]`, and diffs it against the
    instances that currently have `parent_id == root_instance_id`:

    - a desired child whose full id (`f"{root_instance_id}_{local_id}"`) already exists gets its
      params + transform UPDATED in place (its own instance id and any grandchildren survive);
    - a desired child with no existing instance of that id gets CREATED;
    - an existing child of this root that is no longer desired gets REMOVED.

    NESTED assembly-templates (2026-08-04): once a child is created/updated, if that child's OWN
    `subsystem_type` ALSO declares `assembly_children` (i.e. it's itself an assembly-template
    instance, not a leaf part), this function recurses into reconciling THAT child's own children
    too — so a single top-level `reconcile_children()` call fully materializes an arbitrarily-deep
    tree of nested assembly-templates, not just one level. `_ancestor_types` is private recursion
    bookkeeping (the chain of subsystem TYPES already being reconciled on the path down to this
    call, this instance's own type included) — every pre-existing call site (`add_instance`,
    `reconcile_all`, every test) passes just `(ledger, root_instance_id)` and is unaffected.

    Guarded against infinite recursion: if a desired child's `subsystem_type` already appears in
    `_ancestor_types`, that subsystem type would (directly or transitively) contain itself as a
    descendant — raised immediately as a `ValueError` naming the offending type and the ancestor
    chain, instead of recursing forever / hitting Python's own `RecursionError`.

    Returns a new ledger (`model_copy`) — `ledger.instances` is never mutated in place.
    """
    from packages.ledger.schema import Instance
    from packages.subsystems import get_subsystem_model

    inst = ledger.instances[root_instance_id]
    model = get_subsystem_model(inst.subsystem_type)
    if model.assembly_children is None:
        return ledger

    ancestor_types = _ancestor_types + (inst.subsystem_type,)

    ns = resolve_namespace(model, ledger, root_instance_id)
    desired = model.assembly_children(ns)
    for spec in desired:
        if "." in spec.local_id:
            raise ValueError(f"ChildSpec.local_id must not contain '.': {spec.local_id!r}")

    # Scope to children THIS TEMPLATE manages, not every instance merely parented under the root.
    # A sibling added independently (e.g. via instance_ops, composing an unrelated multi-part
    # assembly while an assembly-template instance like "table" happens to be the active root)
    # legitimately has parent_id == root_instance_id too, but was never created by this reconcile
    # loop — its id won't match the f"{root_instance_id}_{local_id}" naming scheme this function
    # itself always uses (see the `child_id` construction below). Filtering existing_children to
    # that same prefix means such a sibling is never mistaken for a stale generated child and
    # deleted — a real bug this exact fix closes (confirmed live: composing a second assembly
    # while a "table" project was active silently deleted the new parts on the next read).
    _prefix = f"{root_instance_id}_"
    existing_children = {
        iid: existing
        for iid, existing in ledger.instances.items()
        if existing.parent_id == root_instance_id and iid.startswith(_prefix)
    }

    new_instances = dict(ledger.instances)
    desired_ids: set[str] = set()
    for spec in desired:
        child_id = f"{root_instance_id}_{spec.local_id}"
        desired_ids.add(child_id)
        child_model = get_subsystem_model(spec.subsystem_type)
        known = {p.name for p in child_model.params}
        unknown = set(spec.params) - known
        if unknown:
            raise KeyError(
                f"unknown params for child subsystem {spec.subsystem_type!r}: {sorted(unknown)}. "
                f"Known: {sorted(known)}"
            )
        params: dict[str, ParameterDef] = {}
        for p in child_model.params:
            v = spec.params.get(p.name, p.value)
            params[p.name] = ParameterDef(value=float(v), unit=p.unit, bounds=(p.min, p.max))

        if child_id in existing_children:
            new_instances[child_id] = existing_children[child_id].model_copy(
                update={
                    "subsystem_type": spec.subsystem_type,
                    "params": params,
                    "transform": spec.transform,
                }
            )
        else:
            new_instances[child_id] = Instance(
                id=child_id,
                subsystem_type=spec.subsystem_type,
                params=params,
                transform=spec.transform,
                parent_id=root_instance_id,
            )

    for child_id in existing_children:
        if child_id not in desired_ids:
            del new_instances[child_id]

    ledger = ledger.model_copy(update={"instances": new_instances})

    # Nested assembly-templates: recurse into any child that is ITSELF an assembly-template
    # instance (its own subsystem_type also declares assembly_children). The child instance already
    # exists in `ledger.instances` at this point (created/updated above), so the recursive call's own
    # `ledger.instances[root_instance_id]` lookup succeeds immediately.
    for spec in desired:
        child_model = get_subsystem_model(spec.subsystem_type)
        if child_model.assembly_children is None:
            continue  # leaf part — no children of its own, nothing to recurse into
        if spec.subsystem_type in ancestor_types:
            raise ValueError(
                f"assembly-template self-nesting detected: subsystem_type {spec.subsystem_type!r} "
                f"would (directly or transitively) contain itself as a descendant — ancestor chain "
                f"{' -> '.join(ancestor_types)} -> {spec.subsystem_type!r} "
                f"(at instance {root_instance_id!r}'s child {spec.local_id!r}). "
                f"A subsystem type must not contain itself in its own assembly_children tree."
            )
        child_id = f"{root_instance_id}_{spec.local_id}"
        ledger = reconcile_children(ledger, child_id, _ancestor_types=ancestor_types)

    return ledger


def reconcile_all(ledger: "MasterParametricLedger") -> "MasterParametricLedger":
    """Reconcile EVERY instance in the tree against its own subsystem's `assembly_children` (not just
    the ledger root) — a no-op instance-by-instance for anything that isn't an assembly-template
    subsystem. This is what makes a live param mutation on an already-materialized `table`/
    `standoff_frame` instance (any master param, e.g. `leg_height_mm`, `leg_count`) converge its
    children on read, regardless of whether that instance happens to be the ledger root or was added
    as a child elsewhere via `add_instance`. Safe to call on every read (`SessionState.ledger()`):
    `reconcile_children` is idempotent and a fast no-op on an already-converged tree.

    NESTED assembly-templates (2026-08-04): this function's own loop is still a single pass over
    `ledger.instances`, but that's sufficient — `reconcile_children` itself now recurses into a
    child's own `assembly_children` (see its docstring), so ONE `reconcile_children` call, on
    whichever instance is the outermost assembly-template touched, fully materializes however many
    levels of nested assembly-template instances exist beneath it. This loop can end up calling
    `reconcile_children` again on an instance that recursion already reconciled (e.g. it still shows
    up in this loop's `list(ledger.instances)` snapshot from a prior read) — harmless, since
    `reconcile_children` is idempotent; just some redundant no-op work, not a correctness bug. A
    subsystem type that (directly or transitively) contains itself is rejected with a clear
    `ValueError` (raised from `reconcile_children`) rather than recursing forever.
    """
    from packages.subsystems import get_subsystem_model

    for instance_id in list(ledger.instances):
        inst = ledger.instances.get(instance_id)
        if inst is None:
            continue  # removed by an earlier reconcile in this same pass
        model = get_subsystem_model(inst.subsystem_type)
        if model.assembly_children is not None:
            ledger = reconcile_children(ledger, instance_id)

    return ledger
