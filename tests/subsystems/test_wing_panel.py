"""Wing panel — half-span tapered NACA panel, root (max chord) at the inner/body end, single taper to
one outer tip; side_sign picks left/right. `naca_wing`'s single-sided sibling — see wing_panel.py's
module docstring for why it exists (naca_wing used as a side panel makes a lens/football shape)."""

from __future__ import annotations

import importlib.util

import pytest

from packages.subsystems import SUBSYSTEM_REGISTRY, get_subsystem

HAS_B123D = importlib.util.find_spec("build123d") is not None


def test_registered_and_airframe_defining():
    assert "wing_panel" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("wing_panel")
    assert sub.name == "wing_panel"
    assert sub.is_airframe_defining is True  # a lifting surface sets part of the outer mold line


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "wing_panel")
    assert get_subsystem("wing_panel").check_invariants(led) == []


def test_positive_volume_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "wing_panel")
    assert get_subsystem("wing_panel").volume_mm3(led) > 0.0


def test_chord_is_monotonic_root_to_tip_not_a_lens():
    # THE bug this subsystem exists to fix: naca_wing's chord is thin-THICK-thin across its span (max
    # at centre). wing_panel's chord must fall monotonically from root_chord at the inner end to
    # tip_chord at the outer end — max at the ROOT, never stranded in the middle.
    from packages.subsystems import get_subsystem_model
    from packages.subsystems.wing_panel import _chord_at
    from packages.subsystems.base import Namespace
    from packages.ledger.parameter import ParameterDef
    sub = get_subsystem_model("wing_panel")
    resolved = {s.name: ParameterDef(value=s.value, unit=s.unit, bounds=(s.min, s.max)) for s in sub.params}
    ns = Namespace(resolved)
    chords = [_chord_at(d, ns) for d in (0.0, ns.span_mm * 0.25, ns.span_mm * 0.5, ns.span_mm * 0.75, ns.span_mm)]
    assert chords[0] == ns.root_chord_mm  # max at the root
    assert chords[-1] == ns.tip_chord_mm  # min at the tip
    assert all(chords[i] >= chords[i + 1] for i in range(len(chords) - 1)), f"not monotonic: {chords}"


def test_reversed_taper_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "wing_panel", root_chord_mm=(60.0, 20.0, 600.0), tip_chord_mm=(120.0, 10.0, 600.0))
    reasons = get_subsystem("wing_panel").check_invariants(led)
    assert any("root_chord_mm" in r and "tip_chord_mm" in r for r in reasons)


def test_tip_too_thin_violates_min_wall(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "wing_panel", tip_chord_mm=(10.0, 10.0, 600.0), thickness_pct=(6.0, 6.0, 21.0))
    reasons = get_subsystem("wing_panel").check_invariants(led)
    assert any("max thickness at the tip" in r for r in reasons)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_right_and_left_build_valid_solids_mirrored():
    from packages.subsystems import get_subsystem_model
    sub = get_subsystem_model("wing_panel")

    class P: ...
    def mk(side):
        p = P()
        for s in sub.params:
            setattr(p, s.name, s.value)
        p.side_sign = side
        return p

    right = sub.build(mk(1.0)).solid
    left = sub.build(mk(-1.0)).solid
    assert right.is_valid and left.is_valid
    assert len(right.solids()) == 1 and len(left.solids()) == 1
    rbb, lbb = right.bounding_box(), left.bounding_box()
    # root at x=0 for BOTH; right extends +X, left extends -X
    assert abs(rbb.min.X) < 1e-3 and rbb.max.X > 0
    assert abs(lbb.max.X) < 1e-3 and lbb.min.X < 0
    # sweep stays AFT on both sides (same-sign max Y) — a matched pair, not a rotated one that would
    # flip the left panel's sweep forward
    assert (rbb.max.Y > 0) == (lbb.max.Y > 0)
    assert abs(rbb.max.Y - lbb.max.Y) < 1e-3


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_and_tags_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "wing_panel")
    part = get_subsystem("wing_panel").geometry_builder(led)
    assert part.solid is not None and part.solid.is_valid
    assert len(part.solid.solids()) == 1
    assert "wing_panel.body" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_volume_approximates_real_build_within_tolerance(base_ledger, seeded):
    led = seeded(base_ledger, "wing_panel")
    approx = get_subsystem("wing_panel").volume_mm3(led)
    real = get_subsystem("wing_panel").geometry_builder(led).solid.volume
    assert abs(approx - real) / real < 0.05
