"""Shared fixtures for the pure-Python backbone tests."""

from __future__ import annotations

import pytest

from packages.ledger.parameter import LockState, ParameterDef
from packages.ledger.schema import (
    Domains,
    GlobalConstraints,
    ManufacturingDomain,
    MasterParametricLedger,
    ProjectMetadata,
    StructureDomain,
)


def make_pd(value: float, lo: float, hi: float, lock: LockState = LockState.DYNAMIC) -> ParameterDef:
    return ParameterDef(value=value, unit="mm", bounds=(lo, hi), lock_state=lock)


def build_ledger(skin_bounds: tuple[float, float] = (1.0, 5.0)) -> MasterParametricLedger:
    return MasterParametricLedger(
        project_metadata=ProjectMetadata(project_id="p1", version_commit="v0", branch="main"),
        global_constraints=GlobalConstraints(factor_of_safety_floor=1.5),
        domains=Domains(
            structure=StructureDomain(
                material_profile="PLA",
                skin_thickness_mm=make_pd(2.0, *skin_bounds),
                internal_rib_spacing_mm=make_pd(20.0, 10.0, 50.0),
            ),
            manufacturing=ManufacturingDomain(
                build_orientation_deg=make_pd(0.0, 0.0, 90.0),
                slip_fit_clearance_mm=make_pd(0.2, 0.0, 1.0),
            ),
        ),
    )


@pytest.fixture
def base_ledger() -> MasterParametricLedger:
    return build_ledger()


@pytest.fixture
def ledger_factory():
    return build_ledger


@pytest.fixture
def pd_factory():
    return make_pd
