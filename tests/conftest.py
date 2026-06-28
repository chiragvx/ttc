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
                plate_width_mm=make_pd(60.0, 40.0, 120.0),
                plate_depth_mm=make_pd(40.0, 30.0, 80.0),
            ),
            manufacturing=ManufacturingDomain(
                build_orientation_deg=make_pd(0.0, 0.0, 90.0),
                slip_fit_clearance_mm=make_pd(0.2, 0.0, 1.0),
                hole_diameter_mm=make_pd(6.0, 3.0, 10.0),
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


# --- a TEST-ONLY deterministic provider (the product ships no mock) ----------
import re  # noqa: E402

from packages.agents.llm_provider import LLMProvider  # noqa: E402
from packages.ledger.deltas import DeltaProposal, ParameterDelta  # noqa: E402
from packages.ledger.nodes import RIB, SKIN  # noqa: E402

_NUM = re.compile(r"(\d+(?:\.\d+)?)")


class StubProvider(LLMProvider):
    """Deterministic intent->delta for tests only. NOT shipped; lives under tests/."""

    def propose_delta(self, *, system: str, conversation: list[dict], ledger_json: str) -> DeltaProposal:
        text = (conversation[-1]["content"] if conversation else "").lower()
        m = _NUM.search(text)
        if "skin" in text and m:
            return DeltaProposal(deltas=[ParameterDelta(target_node=SKIN, requested_value=float(m.group(1)))])
        if "rib" in text and m:
            return DeltaProposal(deltas=[ParameterDelta(target_node=RIB, requested_value=float(m.group(1)))])
        return DeltaProposal(request_clarification="Which parameter and value?")


@pytest.fixture
def stub_provider() -> StubProvider:
    return StubProvider()
