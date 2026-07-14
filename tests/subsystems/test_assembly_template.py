"""Assembly-template mechanism (`packages/subsystems/assembly_template.py::reconcile_children`).

Uses a SYNTHETIC master + child `Subsystem` pair registered in this file (not `table.py` — that's
being migrated in parallel and doesn't exist in this shape yet). Pure-Python: no build123d import
anywhere in this file, matching `reconcile_children`'s own module-scope convention.
"""

from __future__ import annotations

import pytest

from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Instance, Transform
from packages.subsystems import ParamSpec, Subsystem, get_subsystem, register_subsystem
from packages.subsystems.assembly_template import reconcile_children
from packages.subsystems.base import ChildSpec

# ------- synthetic fixtures: a "master" assembly-template subsystem + its "leg" child -------

_LEG = register_subsystem(Subsystem(
    name="_test_at_leg",
    description="synthetic child for assembly-template tests",
    fragment="test fragment",
    disciplines=(),
    params=[
        ParamSpec("leg_height_mm", value=10.0, min=1.0, max=100.0, unit="mm"),
        ParamSpec("leg_dia_mm", value=5.0, min=1.0, max=50.0, unit="mm"),
    ],
))


def _master_children(p):
    n = int(p.leg_count)
    return [
        ChildSpec(
            local_id=f"leg{i}",
            subsystem_type="_test_at_leg",
            transform=Transform(x_mm=float(i) * 10.0),
            params={"leg_height_mm": p.leg_height_mm},
        )
        for i in range(n)
    ]


_MASTER = register_subsystem(Subsystem(
    name="_test_at_master",
    description="synthetic assembly-template master for assembly-template tests",
    fragment="test fragment",
    disciplines=(),
    params=[
        ParamSpec("leg_count", value=2.0, min=1.0, max=8.0, unit="count"),
        ParamSpec("leg_height_mm", value=20.0, min=1.0, max=100.0, unit="mm"),
    ],
    build=None,
    assembly_children=_master_children,
))


def _bad_param_children(p):
    return [
        ChildSpec(
            local_id="leg0",
            subsystem_type="_test_at_leg",
            transform=Transform(),
            params={"bogus_param": 1.0},
        )
    ]


_BAD_MASTER = register_subsystem(Subsystem(
    name="_test_at_bad_master",
    description="synthetic assembly-template master with a typo'd child param",
    fragment="test fragment",
    disciplines=(),
    params=[],
    build=None,
    assembly_children=_bad_param_children,
))


def _seed(base_ledger, name):
    return get_subsystem(name).seed_defaults(base_ledger)


# ------- (a) fresh reconcile creates the right children -------

def test_reconcile_creates_children_with_right_params_and_transform(base_ledger):
    led = _seed(base_ledger, "_test_at_master")
    root_id = led.root_id
    led = reconcile_children(led, root_id)

    assert f"{root_id}_leg0" in led.instances
    assert f"{root_id}_leg1" in led.instances
    leg0 = led.instances[f"{root_id}_leg0"]
    leg1 = led.instances[f"{root_id}_leg1"]

    assert leg0.subsystem_type == "_test_at_leg"
    assert leg0.parent_id == root_id
    assert leg0.params["leg_height_mm"].value == 20.0  # from master's leg_height_mm default
    assert leg0.params["leg_dia_mm"].value == 5.0       # child's own ParamSpec default (no override)
    assert leg0.transform.x_mm == 0.0
    assert leg1.transform.x_mm == 10.0


# ------- (a2) regression: an unrelated sibling parented under the root must survive reconcile -------

def test_reconcile_does_not_delete_an_unrelated_sibling_of_the_root(base_ledger):
    """Confirmed live (2026-07-04): composing a SEPARATE multi-part assembly (e.g. via instance_ops,
    adding an `enclosure`/`bracket`/etc.) while an assembly-template instance (e.g. `table`) happens to
    be the ACTIVE ledger root silently deleted the newly-added parts on the very next read. Root cause:
    `existing_children` scoped only by `parent_id == root_instance_id`, which also matches a legitimate,
    independently-added sibling with a DIFFERENT naming scheme — reconcile_children then treated it as a
    stale generated child (not in `desired_ids`) and removed it. The fix scopes `existing_children` to
    ALSO require the `f"{root}_{local_id}"` id prefix this function itself always uses, so a sibling
    named e.g. "enclosure_1" (not "{root}_enclosure_1") is never touched."""
    led = _seed(base_ledger, "_test_at_master")
    root_id = led.root_id
    led = reconcile_children(led, root_id)  # materializes root's own {root}_leg0/{root}_leg1

    # an unrelated instance, independently parented under the SAME root, NOT following the
    # template's "{root}_{local_id}" naming scheme (mirrors add_instance's own auto-id scheme)
    sibling_id = "_test_at_leg_1"
    new_instances = dict(led.instances)
    new_instances[sibling_id] = Instance(
        id=sibling_id, subsystem_type="_test_at_leg",
        params={"leg_height_mm": ParameterDef(value=42.0, unit="mm", bounds=(1.0, 100.0)),
                "leg_dia_mm": ParameterDef(value=7.0, unit="mm", bounds=(1.0, 50.0))},
        transform=None, parent_id=root_id,
    )
    led = led.model_copy(update={"instances": new_instances})

    # reconciling AGAIN (as every SessionState.ledger() read does via reconcile_all) must not drop it
    led = reconcile_children(led, root_id)

    assert sibling_id in led.instances
    assert led.instances[sibling_id].params["leg_height_mm"].value == 42.0
    # the template's own children are untouched
    assert f"{root_id}_leg0" in led.instances
    assert f"{root_id}_leg1" in led.instances


# ------- (b) re-reconciling after a master param change updates existing children -------

def test_reconcile_after_param_change_updates_children_without_duplicating(base_ledger):
    led = _seed(base_ledger, "_test_at_master")
    root_id = led.root_id
    led = reconcile_children(led, root_id)
    before_count = len(led.instances)

    new_instances = dict(led.instances)
    root = new_instances[root_id]
    new_bag = dict(root.params)
    new_bag["leg_height_mm"] = new_bag["leg_height_mm"].model_copy(update={"value": 55.0})
    new_instances[root_id] = root.model_copy(update={"params": new_bag})
    led = led.model_copy(update={"instances": new_instances})

    led = reconcile_children(led, root_id)

    assert len(led.instances) == before_count  # no duplicates
    assert led.instances[f"{root_id}_leg0"].params["leg_height_mm"].value == 55.0
    assert led.instances[f"{root_id}_leg1"].params["leg_height_mm"].value == 55.0


# ------- (b2) cut_features on a child are a local customization — a master param resync must not
# wipe them (2026-07-04: this is a real trap, not a hypothetical — editing e.g. a table's
# leg_height_mm re-syncs every child's params/transform on every read via reconcile_all/
# SessionState.ledger(), and would silently blow away a hole someone added to a child if the update
# path ever touched cut_features) -------

def test_reconcile_after_param_change_preserves_existing_cut_features(base_ledger):
    from packages.ledger.schema import CutFeature

    led = _seed(base_ledger, "_test_at_master")
    root_id = led.root_id
    led = reconcile_children(led, root_id)

    leg0_id = f"{root_id}_leg0"
    feature = CutFeature(id="leg0_cut0", kind="hole", shape="circle", dia_mm=2.0, depth_mm=3.0)
    new_instances = dict(led.instances)
    new_instances[leg0_id] = new_instances[leg0_id].model_copy(update={"cut_features": [feature]})
    led = led.model_copy(update={"instances": new_instances})

    # a master param change -> re-reconcile, exactly what SessionState.ledger()'s unconditional
    # reconcile_all(self.log.fold()) does on every read (not just an explicit user action)
    new_instances = dict(led.instances)
    root = new_instances[root_id]
    new_bag = dict(root.params)
    new_bag["leg_height_mm"] = new_bag["leg_height_mm"].model_copy(update={"value": 77.0})
    new_instances[root_id] = root.model_copy(update={"params": new_bag})
    led = led.model_copy(update={"instances": new_instances})

    led = reconcile_children(led, root_id)

    leg0 = led.instances[leg0_id]
    assert leg0.params["leg_height_mm"].value == 77.0   # params DID resync from the master
    assert leg0.cut_features == [feature]                # the user-added cut survived the resync


# ------- (c) count-changing master param removes stale children and adds new ones -------

def test_reconcile_after_count_change_adds_and_removes_children(base_ledger):
    led = _seed(base_ledger, "_test_at_master")
    root_id = led.root_id
    led = reconcile_children(led, root_id)

    def _with_count(led, n):
        new_instances = dict(led.instances)
        root = new_instances[root_id]
        new_bag = dict(root.params)
        new_bag["leg_count"] = new_bag["leg_count"].model_copy(update={"value": float(n)})
        new_instances[root_id] = root.model_copy(update={"params": new_bag})
        return led.model_copy(update={"instances": new_instances})

    # grow 2 -> 3
    led = _with_count(led, 3)
    led = reconcile_children(led, root_id)
    for i in range(3):
        assert f"{root_id}_leg{i}" in led.instances

    # shrink 3 -> 1
    led = _with_count(led, 1)
    led = reconcile_children(led, root_id)
    assert f"{root_id}_leg0" in led.instances
    assert f"{root_id}_leg1" not in led.instances
    assert f"{root_id}_leg2" not in led.instances


# ------- (d) non-assembly-template instance: safe no-op -------

def test_reconcile_on_non_assembly_template_instance_is_a_no_op(base_ledger):
    led = _seed(base_ledger, "standoff")
    root_id = led.root_id
    before = dict(led.instances)

    result = reconcile_children(led, root_id)

    assert result.instances == before


# ------- (e) unknown child param name raises KeyError -------

def test_reconcile_unknown_child_param_raises_keyerror(base_ledger):
    led = _seed(base_ledger, "_test_at_bad_master")
    root_id = led.root_id
    with pytest.raises(KeyError):
        reconcile_children(led, root_id)
