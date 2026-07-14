"""Table — assembly-template composite (flat_bar top + N round_post legs as REAL sibling
Instances, not fused geometry). Migrated 2026-07-03 alongside the assembly-template mechanism
(`packages/subsystems/assembly_template.py`)."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.subsystems import get_subsystem
from packages.subsystems.assembly_template import reconcile_children

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _seed_and_reconcile(base_ledger, seeded, **overrides):
    """Seed "table"'s defaults into the root instance, then reconcile so its assembly-template
    children ("root_top", "root_leg0", ...) actually materialize. `seeded`/`seeded_with` (see
    tests/subsystems/conftest.py) only seed the ROOT instance's params — they route through
    `Subsystem.seed_defaults` -> `seed_ledger_geometry`, which does NOT call `reconcile_children`
    (only `packages.subsystems.add_instance` and `packages.ledger.apply.apply_instance_op` do, per
    the assembly-template core report). So every test here reconciles explicitly after seeding."""
    led = seeded(base_ledger, "table", **overrides) if overrides else seeded(base_ledger, "table")
    return reconcile_children(led, led.root_id)


def test_table_registered():
    assert get_subsystem("table").name == "table"


def test_reconcile_creates_top_and_four_legs(base_ledger, seeded):
    led = _seed_and_reconcile(base_ledger, seeded)
    root_id = led.root_id
    assert f"{root_id}_top" in led.instances
    for i in range(4):
        assert f"{root_id}_leg{i}" in led.instances
    top = led.instances[f"{root_id}_top"]
    assert top.subsystem_type == "flat_bar"
    assert top.params["length_mm"].value == 120.0
    assert top.params["width_mm"].value == 80.0
    assert top.params["thickness_mm"].value == 8.0
    leg0 = led.instances[f"{root_id}_leg0"]
    assert leg0.subsystem_type == "round_post"
    assert leg0.params["dia_mm"].value == 12.0
    assert leg0.params["height_mm"].value == 60.0


def test_volume_is_sum_of_children_top_and_legs(base_ledger, seeded):
    """The root's OWN volume is now 0.0 (build=None, volume=None — its children carry the real
    geometry); mass telemetry sums `volume_mm3` over every instance in the tree (see
    packages/transport/app.py `_telemetry`), so the equivalent of the old "table volume" assertion
    is the SUM of volume_mm3 across the reconciled children."""
    led = _seed_and_reconcile(base_ledger, seeded)
    root_id = led.root_id

    # The root instance itself must report zero — else mass would double-count against its children.
    assert get_subsystem("table").volume_mm3(led, root_id) == 0.0

    top_v = get_subsystem("flat_bar").volume_mm3(led, f"{root_id}_top")
    legs_v = sum(
        get_subsystem("round_post").volume_mm3(led, f"{root_id}_leg{i}") for i in range(4)
    )
    total = top_v + legs_v

    expected_top = 120 * 80 * 8
    expected_legs = 4 * math.pi * (6.0**2) * 60
    assert total == pytest.approx(expected_top + expected_legs)


def test_invariant_legs_overrun_footprint(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "table", leg_inset_mm=(60, 2, 80))
    assert any("overruns" in r for r in get_subsystem("table").check_invariants(led))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_render_assembly_produces_five_separate_solids_not_fused(base_ledger, seeded):
    """THE fix for the original bug: legs must no longer be fused to the tabletop. Before this
    migration, table._build() merged top + 4 legs into a `Compound` inside ONE `TaggedPart`/ledger
    instance via compose() — which itself avoided a boolean union, but every part still lived under
    a single instance rather than as independently-addressable/exportable siblings. Now "table" is
    an assembly-template ROOT with no geometry of its own; its 5 children (1 top + 4 legs) are real
    ledger Instances, and `assembly.render_assembly()` (Phase G) is what actually composes the whole
    tree into one scene. Asserting `len(solids) == 5` on that rendered scene — matching the
    established non-fused-parts pattern in test_assembly.py::test_render_assembly_composes_two_
    instances (`len(solids) >= 2`) — is the direct, prominent proof that the legs and tabletop are
    genuinely distinct bodies, not one fused blob.
    """
    from packages.subsystems.assembly import render_assembly

    led = _seed_and_reconcile(base_ledger, seeded)
    part = render_assembly(led)

    assert part.solid is not None
    solids = list(part.solid.solids())
    # 1 tabletop + 4 legs = 5 genuinely separate solids. This is the whole point of this migration:
    # if the legs were still fused to the top (the original bug), this count would collapse below 5.
    assert len(solids) == 5


def test_table_children_appear_as_own_tag_namespace_in_render(base_ledger, seeded):
    """Each child instance is tagged under its OWN instance id in the rendered assembly (Phase G
    namespacing), not nested under "table" — proof the children are first-class siblings."""
    if not HAS_B123D:
        pytest.skip("needs build123d")
    from packages.subsystems.assembly import render_assembly

    led = _seed_and_reconcile(base_ledger, seeded)
    root_id = led.root_id
    part = render_assembly(led)

    assert any(k.startswith(f"{root_id}_top.") for k in part.tags)
    for i in range(4):
        assert any(k.startswith(f"{root_id}_leg{i}.") for k in part.tags)
