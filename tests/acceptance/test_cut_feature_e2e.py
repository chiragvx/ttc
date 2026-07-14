"""End-to-end acceptance test for the generic cut-feature system (hole/pocket/slot via
`feature_ops` on `DeltaProposal`), proving the actual motivating user story top to bottom with REAL
functions — no mocks — across every layer touched by the multi-stage build:

  ledger schema (`CutFeature`, `FeatureOp`) -> `apply_feature_op` (fit + through-depth resolution +
  single-solid validation via the REAL registered `geometry_builder`) -> subsystem wiring
  (`register_subsystem`'s `_build`/`_volume` closures) -> whole-tree composition
  (`packages.subsystems.assembly.render_assembly`) -> telemetry (mass/volume summed over instances,
  same pattern as `packages/transport/app.py::_telemetry`) -> click-to-select
  (`packages.subsystems.features.list_pickable_features`).

Story: a user has a "table" (the assembly-template subsystem — 1 flat_bar top + N round_post legs as
separate sibling Instances, see `tests/subsystems/test_table_assembly.py`) and asks for "a hole in the
center of the top sized for a Stanley cup" (~90mm diameter, through). This test seeds a table sized
large enough to actually fit a 90mm hole (the default 120x80mm top is too narrow — 80mm depth minus
the fit-check's 3mm margin can't fit a 90mm-diameter footprint; a real "sized for a Stanley cup" table
would be bigger than the tiny unit-test default anyway), then drives the whole pipeline for real.
"""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.apply import ApplyStatus, apply_feature_op
from packages.ledger.deltas import FeatureOp, parameter_delta_tool_schema
from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import MasterParametricLedger
from packages.subsystems import get_subsystem
from packages.subsystems.assembly_template import reconcile_children

HAS_B123D = importlib.util.find_spec("build123d") is not None
pytestmark = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")


def _seed_table(base_ledger: MasterParametricLedger, **overrides) -> MasterParametricLedger:
    """Seed "table"'s defaults into the root instance, override selected top-level params (value,
    min, max), then reconcile so the assembly-template children (top/leg0..legN-1) actually
    materialize. Mirrors `tests/subsystems/conftest.py::_seeded_with` + the
    `_seed_and_reconcile` helper in `tests/subsystems/test_table_assembly.py`, reimplemented locally
    since `tests/acceptance/` doesn't inherit fixtures from the sibling `tests/subsystems/`
    directory."""
    led = get_subsystem("table").seed_defaults(base_ledger)
    root_id = led.root_id
    root = led.instances[root_id]
    new_bag = dict(root.params)
    for name, (v, lo, hi) in overrides.items():
        new_bag[name] = ParameterDef(value=v, unit="mm", bounds=(lo, hi))
    new_root = root.model_copy(update={"params": new_bag})
    led = led.model_copy(update={"instances": {**led.instances, root_id: new_root}})
    return reconcile_children(led, root_id)


def _build_part(ledger: MasterParametricLedger, instance_id: str):
    """The injected `build_part` callable `apply_feature_op` needs — bound to the REAL registered
    `geometry_builder`, exactly as the transport-layer report says the next stage should construct
    it (and exactly as `tests/ledger/test_feature_ops.py` already does)."""
    inst = ledger.instances[instance_id]
    return get_subsystem(inst.subsystem_type).geometry_builder(ledger, instance_id)


def _total_volume_mm3(ledger: MasterParametricLedger) -> float:
    """Sum of `volume_mm3` across every instance in the tree — the same sum-over-instances pattern
    `packages/transport/app.py::_telemetry` uses for assembly-wide mass telemetry."""
    total = 0.0
    for iid, inst in ledger.instances.items():
        sub = get_subsystem(inst.subsystem_type)
        if sub.volume_mm3 is not None:
            total += sub.volume_mm3(ledger, iid)
    return total


def test_hole_in_table_top_sized_for_a_stanley_cup_end_to_end(base_ledger):
    from packages.subsystems.assembly import render_assembly
    from packages.subsystems.features import list_pickable_features

    # --- 1. seed a table (top big enough to actually take a ~90mm-diameter hole) ------------------
    led = _seed_table(
        base_ledger,
        top_width_mm=(200.0, 60.0, 400.0),
        top_depth_mm=(150.0, 40.0, 300.0),
    )
    root_id = led.root_id
    top_id = f"{root_id}_top"
    assert top_id in led.instances
    top = led.instances[top_id]
    assert top.subsystem_type == "flat_bar"
    assert top.cut_features == []
    top_thickness_mm = top.params["thickness_mm"].value

    n_legs = 4
    leg_ids = [f"{root_id}_leg{i}" for i in range(n_legs)]
    for lid in leg_ids:
        assert lid in led.instances

    # Baseline (pre-cut) truth: solid count, bounding box, and total volume.
    part_before = render_assembly(led)
    solids_before = list(part_before.solid.solids())
    assert len(solids_before) == 1 + n_legs  # 1 top + 4 legs, genuinely separate bodies
    bbox_before = part_before.solid.bounding_box()
    size_before = (bbox_before.size.X, bbox_before.size.Y, bbox_before.size.Z)
    volume_before = _total_volume_mm3(led)

    # --- 2. the actual user ask: "a hole in the center of the top sized for a Stanley cup" --------
    op = FeatureOp(
        op="add_feature",
        instance_id=top_id,
        kind="hole",
        shape="circle",
        dia_mm=90.0,
        through=True,
        x_mm=0.0,
        y_mm=0.0,
        rationale="hole in the center of the top sized for a Stanley cup",
    )
    new_led, outcome = apply_feature_op(led, op, build_part=_build_part)

    # --- 3. the op succeeded, with a concrete resolved depth grounded in the top's real thickness --
    assert outcome.status is ApplyStatus.APPLIED, outcome.message
    assert outcome.feature is not None
    assert outcome.feature.depth_mm > 0
    # through=True resolves depth from the top's OWN built Z-extent (its true thickness) -- concrete,
    # positive, and EXACTLY the host's real material depth. This is the grounded fact `depth_mm`
    # stores and what `swept_volume_mm3`'s analytic mass/volume accounting relies on staying honest;
    # any OCCT-robustness overhang needed to guarantee full penetration of the actual cutter lives
    # entirely inside `apply_cut_features` (packages/subsystems/cut_features.py::OVERHANG_MM) and is
    # never baked into this stored depth (an earlier version inflated it by 1.5x here, which silently
    # overcounted removed material downstream -- see step 5 below).
    assert outcome.feature.depth_mm == pytest.approx(top_thickness_mm)

    stored = new_led.instances[top_id].cut_features
    assert len(stored) == 1
    assert stored[0].id == outcome.feature.id
    assert stored[0].dia_mm == pytest.approx(90.0)
    # the pre-cut ledger is untouched (apply_feature_op returns a NEW ledger)
    assert led.instances[top_id].cut_features == []

    # --- 4. render the WHOLE assembly: same body count, bbox did not grow -------------------------
    part_after = render_assembly(new_led)
    solids_after = list(part_after.solid.solids())
    assert len(solids_after) == len(solids_before) == 1 + n_legs

    bbox_after = part_after.solid.bounding_box()
    size_after = (bbox_after.size.X, bbox_after.size.Y, bbox_after.size.Z)
    for before, after in zip(size_before, size_after):
        assert after <= before + 1e-6  # a hole removes material -- the envelope cannot grow

    # --- 5. total mass/volume telemetry dropped by ~the hole's swept volume -------------------------
    volume_after = _total_volume_mm3(new_led)
    assert volume_after < volume_before

    decrease = volume_before - volume_after
    analytic_swept = math.pi * (45.0 ** 2) * top_thickness_mm  # pi*(dia/2)^2 * actual thickness
    assert decrease > 0
    # `depth_mm` is now the TRUE host thickness (see step 3), so the analytic swept volume and the
    # REAL OCCT-computed removed volume should agree tightly -- a real through-hole in a uniform slab
    # removes exactly footprint_area * thickness, no more (the cutter's small internal OCCT-robustness
    # overhang extends into empty space below the part, removing nothing extra). A loose ballpark
    # tolerance here would silently re-permit the analytic-vs-real mismatch this test exists to catch.
    assert decrease == pytest.approx(analytic_swept, rel=0.02)

    # --- 6. the cut is visible to the existing click-to-select feature list, unmodified ------------
    features = list_pickable_features(new_led)
    cut_tag = f"cut[{outcome.feature.id}].feature"
    matches = [f for f in features if f["instance_id"] == top_id and f["tag"] == cut_tag]
    assert len(matches) == 1
    match = matches[0]
    assert "center" in match["meta"]
    assert match["meta"]["center"][0] == pytest.approx(0.0)
    assert match["meta"]["center"][1] == pytest.approx(0.0)
    assert match["meta"]["kind"] == "hole"
    assert match["meta"]["shape"] == "circle"
    assert match["meta"]["dia"] == pytest.approx(90.0)

    # Same feature list must NOT have shown this tag before the cut existed.
    features_before = list_pickable_features(led)
    assert not any(f["instance_id"] == top_id and f["tag"] == cut_tag for f in features_before)


def test_feature_ops_reaches_the_llm_tool_schema():
    """Bonus (task item 7): confirm `propose_parameter_delta`'s JSON schema, as actually sent to the
    LLM API, includes `feature_ops`. Already covered directly by
    `tests/ledger/test_feature_ops.py::test_feature_ops_present_in_tool_schema` (the delta-contract
    stage) -- this is a light non-duplicating confirmation that the coverage exists and holds here
    too, from the acceptance-test layer."""
    schema = parameter_delta_tool_schema()
    assert "feature_ops" in schema["properties"]
    assert schema["properties"]["feature_ops"]["type"] == "array"
