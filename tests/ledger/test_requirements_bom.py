"""Requirements matrix, positioned BOM (mass/CG), material DB, datum frame."""

from __future__ import annotations

import math

from packages.ledger.bom import BOM, Component, ComponentKind, material
from packages.ledger.datum import MacReference, Placement
from packages.ledger.requirements import (
    Requirement,
    ReqStatus,
    VerificationMatrix,
    VerificationMethod,
)

FS = Requirement("R1", "FS >= 1.5", "factor_of_safety", ">=", 1.5,
                 allocated_to=("domains.structure.skin_thickness_mm",))
MASS = Requirement("R2", "mass <= 200 g", "mass_g", "<=", 200.0, method=VerificationMethod.TEST)
MATRIX = VerificationMatrix([FS, MASS])


def test_matrix_satisfied_and_score():
    metrics = {"factor_of_safety": 4.05, "mass_g": 150.0}
    assert MATRIX.score(metrics) == 2
    assert not MATRIX.unmet(metrics)


def test_unknown_metric_blocks_not_assumed_ok():
    res = MATRIX.evaluate({"factor_of_safety": None, "mass_g": 150.0})
    statuses = {r.requirement.id: r.status for r in res}
    assert statuses["R1"] is ReqStatus.UNKNOWN  # never assumed satisfied
    assert statuses["R2"] is ReqStatus.SATISFIED


def test_violation_detected():
    assert MATRIX.score({"factor_of_safety": 1.2, "mass_g": 250.0}) == 0


def test_traceability_affected_by():
    reqs = MATRIX.affected_by("domains.structure.skin_thickness_mm")
    assert [r.id for r in reqs] == ["R1"]  # which requirement a skin change might break


def test_bom_mass_and_cg_hand_computed():
    bom = BOM([
        Component("cellA", 70.0, (0.0, 0.0, 0.0), ComponentKind.POWER),
        Component("cellB", 70.0, (100.0, 0.0, 0.0), ComponentKind.POWER),
        Component("payload", 10.0, (200.0, 0.0, 0.0), ComponentKind.PAYLOAD),
    ])
    assert bom.total_mass_g() == 150.0
    cgx, cgy, cgz = bom.cg_mm()
    assert math.isclose(cgx, 60.0)  # (70*0 + 70*100 + 10*200) / 150
    assert bom.mass_breakdown_g() == {"POWER": 140.0, "PAYLOAD": 10.0}


def test_material_db_gives_density_and_props():
    pla = material("PLA")
    assert pla.youngs_mod_mpa > 0 and pla.yield_mpa > 0
    bom = BOM([Component("x", 1.0, (0, 0, 0))])
    assert math.isclose(bom.printed_mass_g("PLA", 1000.0), 1.24, rel_tol=1e-3)


def test_datum_placement_and_mac():
    p = Placement(translation_mm=(50.0, 0.0, 0.0))
    assert p.to_body((10.0, 0.0, 0.0)) == (60.0, 0.0, 0.0)  # local -> body frame
    mac = MacReference(leading_edge_x_mm=100.0, mac_length_mm=200.0)
    assert math.isclose(mac.percent_mac(168.4), 34.2)  # the PRD's CG = 34.2% MAC
