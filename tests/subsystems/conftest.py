"""Shared fixtures for new-style subsystem tests (Phase B+)."""

from __future__ import annotations

import pytest

from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import MasterParametricLedger
from packages.subsystems import get_subsystem


def _seeded_with(base: MasterParametricLedger, name: str, **overrides) -> MasterParametricLedger:
    """Seed a subsystem's defaults into the ROOT instance's params (Phase G source of truth), then
    override selected params with (widened) bounds. Each override is `(value, min, max)` or
    `(value, min, max, unit)`. Also flips `project_metadata.subsystem_type`."""
    led = get_subsystem(name).seed_defaults(base)
    root_id = led.root_id
    new_instances = dict(led.instances)
    root = new_instances[root_id]
    new_bag = dict(root.params)
    for pname, spec in overrides.items():
        if len(spec) == 3:
            v, lo, hi = spec
            unit = "mm"
        else:
            v, lo, hi, unit = spec
        new_bag[pname] = ParameterDef(value=v, unit=unit, bounds=(lo, hi))
    new_instances[root_id] = root.model_copy(update={"params": new_bag})
    pm = led.project_metadata.model_copy(update={"subsystem_type": name})
    return led.model_copy(update={"project_metadata": pm, "instances": new_instances})


def _seeded(base: MasterParametricLedger, name: str) -> MasterParametricLedger:
    return _seeded_with(base, name)


@pytest.fixture
def seeded():
    return _seeded


@pytest.fixture
def seeded_with():
    return _seeded_with
