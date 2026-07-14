"""Subsystem registry — the physical-assembly axis (bracket today; enclosure/standoff next).

Verifies registry membership, the discipline-matrix mapping (applicable_disciplines), the geometry
builder hook resolves to a real part, and that the subsystem_type selector wires the prompt.
"""

from __future__ import annotations

import importlib.util

import pytest

from packages.agents.prompt_builder import build_system_prompt
from packages.ledger.apply import ApplyStatus, apply_delta
from packages.ledger.deltas import ParameterDelta
from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem


def test_registry_has_bracket():
    assert "bracket" in SUBSYSTEM_REGISTRY
    assert get_subsystem("bracket").name == "bracket"


def test_unknown_subsystem_raises():
    with pytest.raises(KeyError):
        get_subsystem("wing")  # not built yet — must fail loudly, not silently default


def test_bracket_declares_its_disciplines():
    # the matrix cell: which lenses analyze a bracket
    assert set(get_subsystem("bracket").applicable_disciplines) == {"structures", "manufacturing", "thermal"}


def test_bracket_geometry_params_present():
    gp = get_subsystem("bracket").geometry_params
    assert "instances.root.params.skin_thickness_mm" in gp
    assert "instances.root.params.hole_diameter_mm" in gp


def test_default_subsystem_type_is_bracket(base_ledger):
    assert base_ledger.project_metadata.subsystem_type == "bracket"


def test_prompt_uses_subsystem_and_disciplines(base_ledger):
    prompt = build_system_prompt(get_subsystem("bracket"), base_ledger)
    assert "Subsystem: Mounting Bracket" in prompt
    # active disciplines' fragments are folded in
    assert "Structures" in prompt and "Manufacturing" in prompt
    # and the auto-generated param schema
    assert "instances.root.params.skin_thickness_mm" in prompt


@pytest.mark.skipif(importlib.util.find_spec("build123d") is None, reason="needs build123d")
def test_bracket_geometry_builder_produces_part(base_ledger):
    part = get_subsystem("bracket").geometry_builder(base_ledger)
    assert part.solid is not None
    assert "plate.body" in part.tag_keys


# --- cascades: bracket's edge-distance rule (prd4.md §2.2's example, applied here) -------------

HOLE = "instances.root.params.hole_diameter_mm"
DEPTH = "instances.root.params.plate_depth_mm"


def test_bracket_hole_cascade_grows_plate_depth_when_needed(base_ledger):
    # defaults: hole_diameter_mm=6.0, plate_depth_mm=40.0 (edge-distance floor: depth >= hole*3).
    # a 15mm/M12-class hole (well outside hole_diameter_mm's own recommended max of 10) would need
    # depth >= 45 -- more than the default 40 -- so the cascade must grow plate_depth_mm to fit it,
    # instead of the edge-distance invariant CONFLICTing the request outright.
    sub = get_subsystem("bracket")
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=HOLE, requested_value=15.0),
                           domain_checks=sub.check_invariants, cascade_rules=sub.cascades)
    assert out.status is ApplyStatus.APPLIED_ADVISORY  # 15mm is outside hole_diameter_mm's own range
    assert new.instances["root"].params["hole_diameter_mm"].value == 15.0
    assert new.instances["root"].params["plate_depth_mm"].value == 45.0  # cascaded up from 40
    assert len(out.cascades) == 1
    assert out.cascades[0].target == DEPTH
    assert "edge-distance" in out.cascades[0].reason


def test_bracket_hole_cascade_is_a_noop_when_depth_already_sufficient(base_ledger):
    # 8mm needs depth >= 24; the default 40 already clears that -- no cascade should fire.
    sub = get_subsystem("bracket")
    new, out = apply_delta(base_ledger, ParameterDelta(target_node=HOLE, requested_value=8.0),
                           domain_checks=sub.check_invariants, cascade_rules=sub.cascades)
    assert out.status is ApplyStatus.APPLIED
    assert out.cascades == []
    assert new.instances["root"].params["plate_depth_mm"].value == 40.0  # untouched
