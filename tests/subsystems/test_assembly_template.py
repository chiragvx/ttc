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


# ------- synthetic fixtures for NESTED assembly-templates (2026-08-04): a genuine 2-level nesting
# needs an outer master whose OWN child is itself an assembly-template ("middle"), whose OWN children
# are leaves. Checked first (per the task instructions): none of the real catalog's assembly-template
# composites (table.py, standoff_frame.py, rail_mount_assembly.py) have a nested assembly-template as
# a child — their children (flat_bar, round_post, standoff, mounting_plate_grid) are all leaf parts
# with no `assembly_children` of their own — so no existing combination can exercise this path. This
# is a small TEST-ONLY fixture pair (middle + outer), reusing the `_test_at_leg` leaf fixture already
# defined above instead of inventing a third new type — NOT a real catalog addition. -------

def _nested_middle_children(p):
    """The "middle" assembly-template's own desired children: N `_test_at_leg` leaves — same shape
    as `_master_children` above, just reused one level deeper to prove nesting, not fusion."""
    n = int(p.mid_leg_count)
    return [
        ChildSpec(
            local_id=f"mleg{i}",
            subsystem_type="_test_at_leg",
            transform=Transform(x_mm=float(i) * 5.0),
            params={"leg_height_mm": p.mid_leg_height_mm},
        )
        for i in range(n)
    ]


_NESTED_MIDDLE = register_subsystem(Subsystem(
    name="_test_at_nested_middle",
    description="synthetic assembly-template that is ITSELF a child of another assembly-template",
    fragment="test fragment",
    disciplines=(),
    params=[
        ParamSpec("mid_leg_count", value=2.0, min=1.0, max=8.0, unit="count"),
        ParamSpec("mid_leg_height_mm", value=9.0, min=1.0, max=100.0, unit="mm"),
    ],
    build=None,
    assembly_children=_nested_middle_children,
))


def _nested_outer_children(p):
    """The "outer" master's desired children: one DIRECT `_test_at_leg` leaf plus one "core" child of
    subsystem_type `_test_at_nested_middle` — that "core" instance is ITSELF an assembly-template
    instance, so reconciling `outer` must recurse into reconciling `core`'s own children too."""
    return [
        ChildSpec(
            local_id="direct_leg",
            subsystem_type="_test_at_leg",
            transform=Transform(y_mm=1.0),
            params={"leg_height_mm": p.outer_direct_height_mm},
        ),
        ChildSpec(
            local_id="core",
            subsystem_type="_test_at_nested_middle",
            transform=Transform(z_mm=1.0),
            params={
                "mid_leg_count": p.outer_mid_leg_count,
                "mid_leg_height_mm": p.outer_direct_height_mm,
            },
        ),
    ]


_NESTED_OUTER = register_subsystem(Subsystem(
    name="_test_at_nested_outer",
    description="synthetic 2-level assembly-template master (outer -> middle -> leaf)",
    fragment="test fragment",
    disciplines=(),
    params=[
        ParamSpec("outer_mid_leg_count", value=2.0, min=1.0, max=8.0, unit="count"),
        ParamSpec("outer_direct_height_mm", value=30.0, min=1.0, max=100.0, unit="mm"),
    ],
    build=None,
    assembly_children=_nested_outer_children,
))


# ------- synthetic fixtures for self-nesting cycle detection (2026-08-04) -------

def _self_nest_children(p):
    """Directly contains ITS OWN subsystem_type as a child — the simplest possible cycle."""
    return [
        ChildSpec(local_id="child", subsystem_type="_test_at_self_nest", transform=Transform(), params={}),
    ]


_SELF_NEST = register_subsystem(Subsystem(
    name="_test_at_self_nest",
    description="synthetic DIRECTLY self-nesting assembly-template (must be rejected, not hang)",
    fragment="test fragment",
    disciplines=(),
    params=[],
    build=None,
    assembly_children=_self_nest_children,
))


def _cycle_a_children(p):
    return [ChildSpec(local_id="b", subsystem_type="_test_at_cycle_b", transform=Transform(), params={})]


_CYCLE_A = register_subsystem(Subsystem(
    name="_test_at_cycle_a",
    description="synthetic TRANSITIVELY self-nesting assembly-template, half A of A -> B -> A",
    fragment="test fragment",
    disciplines=(),
    params=[],
    build=None,
    assembly_children=_cycle_a_children,
))


def _cycle_b_children(p):
    return [ChildSpec(local_id="a", subsystem_type="_test_at_cycle_a", transform=Transform(), params={})]


_CYCLE_B = register_subsystem(Subsystem(
    name="_test_at_cycle_b",
    description="synthetic TRANSITIVELY self-nesting assembly-template, half B of A -> B -> A",
    fragment="test fragment",
    disciplines=(),
    params=[],
    build=None,
    assembly_children=_cycle_b_children,
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


# ------- (f) NESTED assembly-templates: a genuine 2-level tree (outer -> middle -> leaf) -------

def test_reconcile_materializes_a_two_level_nested_assembly_template(base_ledger):
    """A single top-level `reconcile_children(led, root_id)` call on the OUTER master must materialize
    not just its own direct children, but also recurse into its "core" child (itself an
    assembly-template instance of type `_test_at_nested_middle`) and materialize ITS children too —
    real grandchild `Instance`s, parented under the middle instance, not the outer root."""
    led = _seed(base_ledger, "_test_at_nested_outer")
    root_id = led.root_id
    led = reconcile_children(led, root_id)

    direct_id = f"{root_id}_direct_leg"
    core_id = f"{root_id}_core"
    assert direct_id in led.instances
    assert core_id in led.instances
    assert led.instances[direct_id].subsystem_type == "_test_at_leg"
    assert led.instances[core_id].subsystem_type == "_test_at_nested_middle"
    assert led.instances[core_id].parent_id == root_id

    # grandchildren: "core"'s OWN children, materialized by the recursive reconcile — NOT visible
    # unless reconcile_children actually recursed into the nested instance.
    mleg0_id = f"{core_id}_mleg0"
    mleg1_id = f"{core_id}_mleg1"
    assert mleg0_id in led.instances
    assert mleg1_id in led.instances
    assert led.instances[mleg0_id].subsystem_type == "_test_at_leg"
    assert led.instances[mleg0_id].parent_id == core_id
    # params flowed outer -> middle -> leaf: outer's default outer_direct_height_mm=30.0 was passed
    # as the middle's mid_leg_height_mm, which the middle then passed down to each leg's leg_height_mm.
    assert led.instances[mleg0_id].params["leg_height_mm"].value == 30.0
    assert led.instances[mleg1_id].params["leg_height_mm"].value == 30.0
    # the middle's own default leg count (2) produced exactly 2 grandchildren, not 3+
    assert f"{core_id}_mleg2" not in led.instances


def test_reconcile_two_level_nesting_resizes_grandchildren_on_outer_param_change(base_ledger):
    """Changing the OUTER master's `outer_mid_leg_count` must cascade through the middle instance and
    resize the LEAF-level grandchildren (add on growth, remove on shrink) — proving the recursive
    reconcile re-runs on every read, not just at creation, exactly like the existing single-level
    count-change test above but one level deeper."""
    led = _seed(base_ledger, "_test_at_nested_outer")
    root_id = led.root_id
    led = reconcile_children(led, root_id)
    core_id = f"{root_id}_core"

    def _with_outer_count(led, n):
        new_instances = dict(led.instances)
        root = new_instances[root_id]
        new_bag = dict(root.params)
        new_bag["outer_mid_leg_count"] = new_bag["outer_mid_leg_count"].model_copy(update={"value": float(n)})
        new_instances[root_id] = root.model_copy(update={"params": new_bag})
        return led.model_copy(update={"instances": new_instances})

    # grow 2 -> 3
    led = _with_outer_count(led, 3)
    led = reconcile_children(led, root_id)
    for i in range(3):
        assert f"{core_id}_mleg{i}" in led.instances

    # shrink 3 -> 1
    led = _with_outer_count(led, 1)
    led = reconcile_children(led, root_id)
    assert f"{core_id}_mleg0" in led.instances
    assert f"{core_id}_mleg1" not in led.instances
    assert f"{core_id}_mleg2" not in led.instances


# ------- (g) infinite self-nesting is detected and rejected, not hung / silently truncated -------

def test_reconcile_rejects_direct_self_nesting(base_ledger):
    """A subsystem type whose own `assembly_children` names itself as a child (`_test_at_self_nest`)
    must raise a clear error instead of recursing forever."""
    led = _seed(base_ledger, "_test_at_self_nest")
    root_id = led.root_id
    with pytest.raises(ValueError, match="self-nest"):
        reconcile_children(led, root_id)


def test_reconcile_rejects_transitive_self_nesting(base_ledger):
    """A -> B -> A: neither `_test_at_cycle_a` nor `_test_at_cycle_b` directly names itself, but A
    transitively contains itself via B — must still be caught (by the ancestor-chain guard, not by
    exhausting the recursion limit) rather than raising a bare `RecursionError`."""
    led = _seed(base_ledger, "_test_at_cycle_a")
    root_id = led.root_id
    with pytest.raises(ValueError, match="self-nest"):
        reconcile_children(led, root_id)
