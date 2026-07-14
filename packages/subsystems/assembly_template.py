"""Assembly-template mechanism (2026-07-03) — turn a "master" Subsystem's params into REAL sibling
`Instance`s in the ledger's instance tree, instead of fused geometry.

A `Subsystem` normally owns its own `build` and produces one solid. An assembly-template Subsystem
instead sets `Subsystem.assembly_children` (and leaves `build=None`) — a callable that reads the
master instance's resolved params and returns the list of `ChildSpec`s it WANTS to exist as children.
`reconcile_children()` is the pure-Python diff/apply step: given a root instance id, it resolves the
desired child list, and reconciles it against whatever children currently exist under that root
(update existing, create missing, remove stale) — so calling it again after a master param change
(e.g. a leg count) converges the tree to the new desired shape without duplicating instances.

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
    ledger: "MasterParametricLedger", root_instance_id: str
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

    Returns a new ledger (`model_copy`) — `ledger.instances` is never mutated in place.
    """
    from packages.ledger.schema import Instance
    from packages.subsystems import get_subsystem_model

    inst = ledger.instances[root_instance_id]
    model = get_subsystem_model(inst.subsystem_type)
    if model.assembly_children is None:
        return ledger

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

    return ledger.model_copy(update={"instances": new_instances})


def reconcile_all(ledger: "MasterParametricLedger") -> "MasterParametricLedger":
    """Reconcile EVERY instance in the tree against its own subsystem's `assembly_children` (not just
    the ledger root) — a no-op instance-by-instance for anything that isn't an assembly-template
    subsystem. This is what makes a live param mutation on an already-materialized `table`/
    `standoff_frame` instance (any master param, e.g. `leg_height_mm`, `leg_count`) converge its
    children on read, regardless of whether that instance happens to be the ledger root or was added
    as a child elsewhere via `add_instance`. Safe to call on every read (`SessionState.ledger()`):
    `reconcile_children` is idempotent and a fast no-op on an already-converged tree.

    Single pass: does not (yet) handle an assembly-template instance whose OWN children are
    themselves assembly-template instances — no such nesting exists in the registry today.
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
