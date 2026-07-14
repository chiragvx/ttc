"""Generic cut-feature primitive (`packages/ledger/schema.py::CutFeature`,
`packages/subsystems/cut_features.py`) — the reusable hole/pocket/slot subtraction usable on ANY
instance of ANY subsystem, wired into `register_subsystem`'s `_build`/`_volume` closures with zero
per-subsystem file changes.
"""

from __future__ import annotations

import importlib.util
import math

import pytest

from packages.ledger.schema import CutFeature
from packages.subsystems import get_subsystem
from packages.subsystems.cut_features import swept_volume_mm3

HAS_B123D = importlib.util.find_spec("build123d") is not None


# --- pure-Python: swept_volume_mm3 needs no OCCT, runs unconditionally ----------------------------

def test_swept_volume_circle_matches_hand_computation():
    f = CutFeature(id="h0", kind="hole", shape="circle", dia_mm=8.0, depth_mm=5.0)
    expected = math.pi * (8.0 / 2.0) ** 2 * 5.0
    assert swept_volume_mm3(f) == pytest.approx(expected)


def test_swept_volume_rect_matches_hand_computation():
    f = CutFeature(id="p0", kind="pocket", shape="rect", length_mm=20.0, width_mm=10.0, depth_mm=3.0)
    expected = 20.0 * 10.0 * 3.0
    assert swept_volume_mm3(f) == pytest.approx(expected)


# --- CutFeature validation (pure pydantic, no OCCT) ------------------------------------------------

def test_circle_without_dia_mm_rejected():
    with pytest.raises(Exception):
        CutFeature(id="h0", kind="hole", shape="circle", depth_mm=5.0)


def test_rect_without_length_or_width_rejected():
    with pytest.raises(Exception):
        CutFeature(id="p0", kind="pocket", shape="rect", length_mm=10.0, depth_mm=5.0)
    with pytest.raises(Exception):
        CutFeature(id="p0", kind="pocket", shape="rect", width_mm=10.0, depth_mm=5.0)


def test_depth_mm_must_be_positive():
    with pytest.raises(Exception):
        CutFeature(id="h0", kind="hole", shape="circle", dia_mm=4.0, depth_mm=0.0)
    with pytest.raises(Exception):
        CutFeature(id="h0", kind="hole", shape="circle", dia_mm=4.0, depth_mm=-1.0)


def test_extra_field_forbidden():
    with pytest.raises(Exception):
        CutFeature(id="h0", kind="hole", shape="circle", dia_mm=4.0, depth_mm=5.0, bogus=1)


# --- apply_cut_features / register_subsystem wiring — needs build123d -----------------------------

pytestmark_b123d = pytest.mark.skipif(not HAS_B123D, reason="needs build123d")


@pytestmark_b123d
def test_apply_cut_features_empty_list_is_noop():
    import build123d as bd

    from packages.subsystems.cut_features import apply_cut_features
    from packages.truth_plane.regen.templated import TaggedPart

    part = TaggedPart(solid=bd.Box(50.0, 30.0, 5.0), tags={"bar.body": {"kind": "solid"}})
    result = apply_cut_features(part, [])
    assert result is part  # exact same object — the fast no-op path


@pytestmark_b123d
def test_apply_cut_features_through_hole_removes_material_and_stays_one_solid():
    import build123d as bd

    from packages.subsystems.cut_features import apply_cut_features
    from packages.truth_plane.regen.templated import TaggedPart

    width, depth, thickness = 50.0, 30.0, 5.0
    part = TaggedPart(solid=bd.Box(width, depth, thickness), tags={"bar.body": {"kind": "solid"}})
    original_volume = part.solid.volume

    dia = 6.0
    cut_depth = thickness * 1.5  # >= host Z-extent -> full penetration
    feature = CutFeature(id="h0", kind="hole", shape="circle", dia_mm=dia, depth_mm=cut_depth)

    result = apply_cut_features(part, [feature])

    assert len(result.solid.solids()) == 1
    assert result.solid.volume < original_volume
    expected_removed = math.pi * (dia / 2.0) ** 2 * thickness  # material actually inside the host
    actual_removed = original_volume - result.solid.volume
    assert actual_removed == pytest.approx(expected_removed, rel=0.05)

    assert "cut[h0].feature" in result.tags
    tag = result.tags["cut[h0].feature"]
    assert tag["kind"] == "hole"
    assert tag["shape"] == "circle"
    assert tag["dia"] == dia
    assert tag["center"] == [0.0, 0.0]
    # host's own pre-existing tag is preserved, not overwritten/namespaced
    assert "bar.body" in result.tags


@pytestmark_b123d
def test_apply_cut_features_severing_cut_raises_value_error():
    import build123d as bd

    from packages.subsystems.cut_features import apply_cut_features
    from packages.truth_plane.regen.templated import TaggedPart

    length, width, thickness = 60.0, 20.0, 4.0
    part = TaggedPart(solid=bd.Box(length, width, thickness), tags={"bar.body": {"kind": "solid"}})

    # a wide rect slot cut clean through the bar's middle severs it into two islands
    slot = CutFeature(
        id="slot0", kind="slot", shape="rect",
        length_mm=5.0, width_mm=width * 2.0, depth_mm=thickness * 1.5,
    )
    with pytest.raises(ValueError):
        apply_cut_features(part, [slot])


@pytestmark_b123d
def test_register_subsystem_wiring_end_to_end(base_ledger, seeded):
    """Attach a CutFeature directly to the root instance of a seeded `flat_bar` and confirm BOTH the
    geometry_builder path and the volume_mm3 path reflect the cut consistently."""
    led = seeded(base_ledger, "flat_bar")
    root = led.instances[led.root_id]
    length = root.params["length_mm"].value
    width = root.params["width_mm"].value
    thickness = root.params["thickness_mm"].value

    sub = get_subsystem("flat_bar")
    base_solid_volume = length * width * thickness
    base_analytic_volume = sub.volume_mm3(led)  # analytic base, BEFORE any cut is attached
    assert base_analytic_volume == pytest.approx(base_solid_volume)

    dia = 4.0
    cut_depth = thickness * 1.5
    feature = CutFeature(id="h0", kind="hole", shape="circle", dia_mm=dia, depth_mm=cut_depth)
    new_root = root.model_copy(update={"cut_features": [feature]})
    new_instances = dict(led.instances)
    new_instances[led.root_id] = new_root
    led = led.model_copy(update={"instances": new_instances})

    part = sub.geometry_builder(led)
    assert "cut[h0].feature" in part.tags
    assert part.solid.volume < base_solid_volume

    reduced_volume = sub.volume_mm3(led, led.root_id)
    expected_removed = math.pi * (dia / 2.0) ** 2 * cut_depth
    assert reduced_volume == pytest.approx(max(0.0, base_solid_volume - expected_removed))
    assert reduced_volume < base_solid_volume
