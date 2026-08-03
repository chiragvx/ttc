"""Cylindrical Grip — a plain solid cylinder (structural envelope only; texture ribs/knurling NOT
modeled, same disclosed-simplification precedent as `knurled_nut`). Bespoke per-part correctness
tests, complementing the generic catalog-wide parametrized build-succeeds-only loop in
test_uav_hardware_catalog.py / test_general_hardware_catalog.py."""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.parameter import ParameterDef
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem, get_subsystem_model
from packages.subsystems.base import Namespace
from packages.subsystems.cylindrical_grip import _check, _volume

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _ns(dia_mm: float, height_mm: float) -> Namespace:
    return Namespace({
        "dia_mm": ParameterDef(value=dia_mm, unit="mm", bounds=(6.0, 60.0)),
        "height_mm": ParameterDef(value=height_mm, unit="mm", bounds=(20.0, 250.0)),
    })


def test_registered():
    assert "cylindrical_grip" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("cylindrical_grip")
    assert sub.name == "cylindrical_grip"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


# --- volume -------------------------------------------------------------------

def test_volume_matches_hand_computed_cylinder_formula():
    # dia_mm=24 -> radius 12mm, height_mm=50mm: solid-cylinder volume is pi * r^2 * h exactly (no
    # bore, no knurl grooves modeled -- the module's own docstring/_build confirm a plain bd.Cylinder).
    ns = _ns(dia_mm=24.0, height_mm=50.0)
    vol = _volume(ns)
    assert vol == pytest.approx(math.pi * 12.0 ** 2 * 50.0)
    assert vol == pytest.approx(22619.46710584651, rel=1e-9)  # hand-computed literal, not re-derived from the formula


def test_volume_at_catalog_defaults_via_the_ledger_facing_adapter(base_ledger, seeded):
    # Cross-check: the SubsystemContext adapter's volume_mm3(ledger) must agree with calling the
    # module's own _volume() directly (dia_mm=20 default -> radius 10mm, height_mm=80mm default).
    led = seeded(base_ledger, "cylindrical_grip")
    vol = get_subsystem("cylindrical_grip").volume_mm3(led)
    assert vol == pytest.approx(math.pi * 10.0 ** 2 * 80.0)
    assert vol == pytest.approx(25132.741228718347, rel=1e-9)


# --- invariants -----------------------------------------------------------------

def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "cylindrical_grip")
    reasons = get_subsystem("cylindrical_grip").check_invariants(led)
    assert reasons == [], f"cylindrical_grip default seeds must satisfy invariants: {reasons}"


def test_too_thin_height_violates_min_wall_via_the_ledger_facing_adapter(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "cylindrical_grip", height_mm=(0.5, 0.1, 50))
    reasons = get_subsystem("cylindrical_grip").check_invariants(led)
    assert reasons != []
    assert any("min wall" in r for r in reasons)


def test_check_called_directly_flags_too_thin_height():
    # The module's own _check(), called directly (not via the ledger-facing adapter) -- exact
    # boundary from the source: `if p.height_mm < 0.8: return [f"height {p.height_mm:.2f} mm < min
    # wall 0.8 mm"]`. dia_mm is irrelevant to this rule -- only height_mm trips it.
    reasons = _check(_ns(dia_mm=20.0, height_mm=0.5))
    assert reasons == ["height 0.50 mm < min wall 0.8 mm"]


def test_check_called_directly_is_clean_at_the_boundary_and_above():
    assert _check(_ns(dia_mm=20.0, height_mm=0.8)) == []  # exactly at the floor -- not "< 0.8"
    assert _check(_ns(dia_mm=20.0, height_mm=80.0)) == []  # catalog default


# --- interfaces / mate frames ---------------------------------------------------

def test_declares_cylinder_end_interfaces():
    assert [i.name for i in get_subsystem_model("cylindrical_grip").interfaces] == ["bottom", "top"]


def test_end_interfaces_land_at_the_exact_expected_coordinates():
    # height_mm=80 (default) -> half-height 40mm: cylinder_end_interfaces() puts "bottom" at local
    # z=-40 (outward normal -Z) and "top" at local z=+40 (outward normal +Z) -- the body is a plain
    # bd.Cylinder(radius=dia_mm/2, height=height_mm) centered at the origin (confirmed by reading
    # _build directly), so the ends sit at +/- height/2 with no rotation.
    ns = _ns(dia_mm=20.0, height_mm=80.0)
    interfaces = {i.name: i for i in get_subsystem_model("cylindrical_grip").interfaces}
    bottom = interfaces["bottom"].frame(ns)
    top = interfaces["top"].frame(ns)
    assert bottom.origin == pytest.approx((0.0, 0.0, -40.0))
    assert bottom.normal == pytest.approx((0.0, 0.0, -1.0))
    assert top.origin == pytest.approx((0.0, 0.0, 40.0))
    assert top.normal == pytest.approx((0.0, 0.0, 1.0))


def test_end_interfaces_track_a_non_default_height():
    # The frame is a CALLABLE over resolved params, not a cached constant -- changing height_mm must
    # move both interfaces with it (dia_mm plays no part in either end's coordinates).
    ns = _ns(dia_mm=20.0, height_mm=150.0)
    interfaces = {i.name: i for i in get_subsystem_model("cylindrical_grip").interfaces}
    assert interfaces["bottom"].frame(ns).origin == pytest.approx((0.0, 0.0, -75.0))
    assert interfaces["top"].frame(ns).origin == pytest.approx((0.0, 0.0, 75.0))


# --- real geometry ----------------------------------------------------------

@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds(base_ledger, seeded):
    led = seeded(base_ledger, "cylindrical_grip")
    part = get_subsystem("cylindrical_grip").geometry_builder(led)
    assert part.solid is not None
    assert "body.cyl" in part.tag_keys
