"""Rail-mount assembly — assembly-template composite (flat_bar rail + N mounting_plate_grid plates
as REAL sibling Instances, not fused geometry). Same live mechanism as `table.py`
(`packages/subsystems/assembly_template.py`). 2026-07-22 — the "a relay box is a rail + plates, not
an empty box" pattern, as one addable catalog part."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import get_subsystem
from packages.subsystems.assembly_template import reconcile_children

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _seed_and_reconcile(base_ledger, seeded, **overrides):
    led = seeded(base_ledger, "rail_mount_assembly", **overrides) if overrides else seeded(base_ledger, "rail_mount_assembly")
    return reconcile_children(led, led.root_id)


def test_rail_mount_assembly_registered():
    assert get_subsystem("rail_mount_assembly").name == "rail_mount_assembly"


def test_reconcile_creates_rail_and_two_plates_by_default(base_ledger, seeded):
    led = _seed_and_reconcile(base_ledger, seeded)
    root_id = led.root_id
    assert f"{root_id}_rail" in led.instances
    assert f"{root_id}_plate0" in led.instances
    assert f"{root_id}_plate1" in led.instances
    assert f"{root_id}_plate2" not in led.instances  # default plate_count=2, no third

    rail = led.instances[f"{root_id}_rail"]
    assert rail.subsystem_type == "flat_bar"
    assert rail.params["length_mm"].value == 220.0
    assert rail.params["thickness_mm"].value == 8.0
    assert rail.transform.z_mm == pytest.approx(4.0)  # rail_height_mm/2, resting on z=0

    plate0 = led.instances[f"{root_id}_plate0"]
    assert plate0.subsystem_type == "mounting_plate_grid"
    assert plate0.params["width_mm"].value == 90.0
    assert plate0.params["thickness_mm"].value == 2.5


def test_plate_count_changes_child_count(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "rail_mount_assembly", plate_count=(4, 1, 8))
    led = reconcile_children(led, led.root_id)
    root_id = led.root_id
    for i in range(4):
        assert f"{root_id}_plate{i}" in led.instances
    assert f"{root_id}_plate4" not in led.instances


def test_plates_are_evenly_spaced_along_the_rail_and_rest_on_top_of_it(base_ledger, seeded):
    led = _seed_and_reconcile(base_ledger, seeded)
    root_id = led.root_id
    plate0 = led.instances[f"{root_id}_plate0"]
    plate1 = led.instances[f"{root_id}_plate1"]
    # default: rail_length_mm=220, plate_width_mm=90 -> margin=45, usable=130, spacing=130
    assert plate0.transform.x_mm == pytest.approx(-65.0)
    assert plate1.transform.x_mm == pytest.approx(65.0)
    # both plates sit on TOP of the rail: rail_height_mm(8) + plate_thickness_mm(2.5)/2
    assert plate0.transform.z_mm == pytest.approx(9.25)
    assert plate1.transform.z_mm == pytest.approx(9.25)


def test_single_plate_sits_centered_on_the_rail(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "rail_mount_assembly", plate_count=(1, 1, 8))
    led = reconcile_children(led, led.root_id)
    plate0 = led.instances[f"{led.root_id}_plate0"]
    assert plate0.transform.x_mm == pytest.approx(0.0)


def test_invariant_plates_overrun_the_rail(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "rail_mount_assembly", rail_length_mm=(60, 60, 500), plate_count=(4, 1, 8))
    assert any("overrun" in r for r in get_subsystem("rail_mount_assembly").check_invariants(led))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_render_assembly_produces_three_separate_solids_not_fused(base_ledger, seeded):
    from packages.subsystems.assembly import render_assembly

    led = _seed_and_reconcile(base_ledger, seeded)
    part = render_assembly(led)
    assert part.solid is not None
    solids = list(part.solid.solids())
    assert len(solids) == 3  # 1 rail + 2 plates (default plate_count)


def test_assembly_does_not_trip_its_own_interference_or_connectivity_checks(base_ledger, seeded):
    # rail + plates have no declared Connections between them (ChildSpec transforms are closed-form,
    # not mate-solved) — confirm the plates-rest-on-rail geometry doesn't self-flag as unexplained
    # overlap now that "interference" exists.
    from packages.truth_plane.validate import validate_geometry

    led = _seed_and_reconcile(base_ledger, seeded)
    report = validate_geometry(led)
    checks_fired = {i.check for i in report.issues}
    assert "interference" not in checks_fired
    assert "connectivity" not in checks_fired
