"""End-to-end acceptance test for general multi-instance assembly composition (`InstanceOp` /
`apply_instance_op`) — reproducing the ACTUAL stress test that motivated the feature: "assemble a
satellite using your parts."

This does NOT test LLM output (nondeterministic) — it drives the DETERMINISTIC machinery an LLM's
`instance_ops` list would trigger, with REAL functions and no mocks, exactly mirroring the injection
shape `packages/transport/app.py`'s `/instance_ops` endpoint binds:

    apply_instance_op(ledger, op, known_subsystem_types=frozenset(SUBSYSTEM_REGISTRY),
                       seed_defaults=<binds to seed_instance(get_subsystem_model(name), id, parent_id)>,
                       reconcile=reconcile_children)

Pipeline exercised end to end: `InstanceOp` (ledger schema) -> `apply_instance_op` (validation +
mutation, ledger stays pure per `packages/ledger/CLAUDE.md`) -> real subsystem registry
(`SUBSYSTEM_REGISTRY` / `get_subsystem_model`) -> whole-tree composition
(`packages.subsystems.assembly.render_assembly` + `instance_world_offsets`) -> assembly-template
reconciliation (`packages.subsystems.assembly_template.reconcile_children`) for the parent/children
rejection sub-case.

Story: the root project is a lone "bracket" (the simplest single-instance seed). The user says
"assemble a satellite using your parts." There is no "satellite" subsystem in the catalog (and never
should be — see CLAUDE.md's cut-list: no orbital mechanics, thermal, radiation, aero, propulsion/range
here) — the copilot instead DECOMPOSES the ask into several EXISTING, already-registered subsystem
types: an `enclosure` (the satellite body/bus), two `round_post`s (an antenna mast + a deployable
strut), a `mounting_plate_grid` (an instrument deck), and a second `bracket` (a mounting bracket for a
payload) — all real names verified against `SUBSYSTEM_REGISTRY` below, none invented.
"""

from __future__ import annotations

import importlib.util

import pytest

from packages.ledger.apply import ApplyStatus, apply_instance_op
from packages.ledger.deltas import InstanceOp
from packages.ledger.schema import Instance, MasterParametricLedger
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems.assembly_template import reconcile_children
from packages.subsystems.base import seed_instance

HAS_B123D = importlib.util.find_spec("build123d") is not None
pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")

KNOWN_SUBSYSTEM_TYPES = frozenset(SUBSYSTEM_REGISTRY)


def _seed_defaults(subsystem_type: str, instance_id: str, parent_id) -> Instance:
    """The REAL `seed_defaults` callable `apply_instance_op` needs, bound exactly as the transport
    layer's report says `/instance_ops` binds it: by subsystem NAME (never a `Subsystem` model
    crossing into packages.ledger) -> `seed_instance(get_subsystem_model(name), id, parent_id=...)`."""
    model = get_subsystem_model(subsystem_type)
    return seed_instance(model, instance_id, parent_id=parent_id)


def _apply(ledger: MasterParametricLedger, op: InstanceOp):
    """Apply one InstanceOp with the real injected callables (seed_defaults + reconcile_children),
    the exact production wiring."""
    return apply_instance_op(
        ledger, op, KNOWN_SUBSYSTEM_TYPES,
        seed_defaults=_seed_defaults, reconcile=reconcile_children,
    )


def test_assemble_a_satellite_using_your_parts_end_to_end(base_ledger):
    from packages.subsystems.assembly import instance_world_offsets, render_assembly

    # --- sanity: every subsystem type this test relies on is a REAL registered name, not invented ---
    satellite_parts = ["enclosure", "round_post", "round_post", "mounting_plate_grid", "bracket"]
    for name in satellite_parts:
        assert name in SUBSYSTEM_REGISTRY, f"{name!r} must be a real registered subsystem"

    # --- 1. fresh single-instance project: a lone "bracket" at the root ------------------------------
    led = base_ledger
    root_id = led.root_id
    assert len(led.instances) == 1
    assert led.instances[root_id].subsystem_type == "bracket"

    # --- 2 & 3. the satellite decomposition: 5 add_instance ops over 4 DIFFERENT real subsystem
    #     types, NO explicit transform on any of them (proving the auto-layout path) ------------------
    ops = [
        InstanceOp(op="add_instance", subsystem_type="enclosure",
                   rationale="satellite body/bus"),
        InstanceOp(op="add_instance", subsystem_type="round_post",
                   rationale="antenna mast"),
        InstanceOp(op="add_instance", subsystem_type="round_post",
                   rationale="deployable strut"),
        InstanceOp(op="add_instance", subsystem_type="mounting_plate_grid",
                   rationale="instrument deck"),
        InstanceOp(op="add_instance", subsystem_type="bracket",
                   rationale="payload mounting bracket"),
    ]
    expected_ids = ["enclosure_1", "round_post_1", "round_post_2", "mounting_plate_grid_1", "bracket_1"]
    expected_types = ["enclosure", "round_post", "round_post", "mounting_plate_grid", "bracket"]

    added_ids = []
    for op, expected_id, expected_type in zip(ops, expected_ids, expected_types):
        led, outcome = _apply(led, op)
        assert outcome.status is ApplyStatus.APPLIED, outcome.message
        assert outcome.instance_id == expected_id
        assert outcome.instance is not None
        assert outcome.instance.subsystem_type == expected_type
        assert outcome.instance.transform is None  # no explicit position was given -> auto-layout
        added_ids.append(outcome.instance_id)

    # --- 3 (cont'd). ledger now has ROOT + every new instance, correct type + default params --------
    assert set(led.instances) == {root_id, *added_ids}
    for iid, expected_type in zip(added_ids, expected_types):
        inst = led.instances[iid]
        assert inst.subsystem_type == expected_type
        # parts are a FLAT set brought into a file (2026-07-04) — omitting parent_id means
        # top-level, never auto-parented under whichever part happened to already exist.
        assert inst.parent_id is None
        model = get_subsystem_model(expected_type)
        expected_defaults = model.defaults()
        assert set(inst.params) == set(expected_defaults)
        for pname, pdef in expected_defaults.items():
            assert inst.params[pname].value == pytest.approx(pdef.value)

    # --- 4. render the WHOLE assembly ----------------------------------------------------------------
    # every chosen subsystem type here (bracket, enclosure, round_post, mounting_plate_grid) has a
    # real geometry_builder (none of them is an assembly-template/master-only type like "table"), so
    # every instance in this scenario contributes SOME geometry. But a subsystem's builder does not
    # necessarily emit exactly one solid per instance (e.g. an enclosure body + its lid can be two
    # separate, unfused solids) — so the expected total is computed by actually invoking each
    # instance's REAL geometry_builder standalone and summing its own solid count, not by guessing
    # "1 solid per instance":
    expected_solid_count = 0
    for iid, inst in led.instances.items():
        builder = get_subsystem(inst.subsystem_type).geometry_builder
        assert builder is not None, f"expected every instance in this scenario to carry real geometry: {iid}"
        standalone_part = builder(led, iid)
        assert standalone_part is not None
        expected_solid_count += len(list(standalone_part.solid.solids()))

    part = render_assembly(led)  # must not raise
    solids = list(part.solid.solids())
    assert len(solids) == expected_solid_count

    # --- auto-layout: every non-root instance sits at a DISTINCT, non-overlapping Y position, across
    #     4+ heterogeneous part types (enclosure, round_post x2, mounting_plate_grid, bracket) --------
    offsets = instance_world_offsets(led)
    assert offsets[root_id] == (0.0, 0.0, 0.0)
    non_root_y = [offsets[iid][1] for iid in added_ids]
    assert len(non_root_y) == len(set(non_root_y)), f"auto-layout produced overlapping Y offsets: {non_root_y}"
    # strictly increasing, since auto-layout stacks along +Y with a fixed gap between EVERY pair
    assert non_root_y == sorted(non_root_y)
    assert all(y > 0.0 for y in non_root_y)

    # --- 5. reject-path: the copilot must NOT be able to fabricate a fictional part type -------------
    for fake_type in ("satellite_body", "orbital_thruster"):
        assert fake_type not in SUBSYSTEM_REGISTRY, (
            f"test setup assumption broken: {fake_type!r} unexpectedly IS a real subsystem"
        )
        bad_op = InstanceOp(op="add_instance", subsystem_type=fake_type,
                             rationale="fabricated domain-specific part — must be rejected")
        rejected_ledger, bad_outcome = _apply(led, bad_op)
        assert bad_outcome.status is ApplyStatus.REJECTED
        assert "unknown subsystem_type" in bad_outcome.message
        # the ledger is untouched — no fictional instance sneaked in
        assert set(rejected_ledger.instances) == set(led.instances)
        assert rejected_ledger.instances.keys() == led.instances.keys()

    # --- 6. remove-with-children rejection: add an assembly-template instance ("table") so it has
    #     REAL children after reconcile, then confirm removing it is rejected ------------------------
    table_op = InstanceOp(op="add_instance", subsystem_type="table",
                          rationale="equipment table for ground support gear")
    led_with_table, table_outcome = _apply(led, table_op)
    assert table_outcome.status is ApplyStatus.APPLIED, table_outcome.message
    table_id = table_outcome.instance_id
    assert table_id == "table_1"

    # reconcile_children (passed as `reconcile`) actually ran and materialized real child instances
    child_ids = [iid for iid, inst in led_with_table.instances.items() if inst.parent_id == table_id]
    assert len(child_ids) > 0, "table's assembly_children should have produced real sibling instances"
    assert f"{table_id}_top" in child_ids

    remove_table_op = InstanceOp(op="remove_instance", instance_id=table_id)
    after_remove_attempt, remove_outcome = _apply(led_with_table, remove_table_op)
    assert remove_outcome.status is ApplyStatus.REJECTED
    assert "has children" in remove_outcome.message
    # nothing was removed — ledger is byte-for-byte the same instance set
    assert set(after_remove_attempt.instances) == set(led_with_table.instances)
