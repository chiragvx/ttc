"""packages/subsystems/regions.py -- a plain geometry helper (needs a real build123d/OCCT kernel,
Linux dev container; skipped on this Windows host, same convention as tests/solvers/test_export.py).
NOT ledger-persisted -- see regions.py's own module docstring for the distinction from
packages/ledger/schema.py::Region."""

from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.needs_kernel

_HAS_KERNEL = importlib.util.find_spec("build123d") is not None


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_leftover_volume_with_no_components_returns_the_whole_cavity_labeled():
    import build123d as bd

    from packages.subsystems.regions import leftover_volume

    cavity = bd.Box(100.0, 80.0, 40.0)
    result = leftover_volume(cavity, [])
    assert len(result) == 1
    assert result[0].label == "leftover_0"
    assert result[0].volume == pytest.approx(cavity.volume, rel=1e-6)


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_leftover_volume_single_component_no_fuse_needed():
    """A single component skips the Fuse loop entirely -- exercised separately from the 2+-component
    Fuse-first path below. Hand-computed: 60^3 - 20^3 = 216,000 - 8,000 = 208,000 mm^3."""
    import build123d as bd

    from packages.subsystems.regions import leftover_volume

    cavity = bd.Box(60.0, 60.0, 60.0)
    comp = bd.Box(20.0, 20.0, 20.0)
    result = leftover_volume(cavity, [comp])
    total_volume = sum(s.volume for s in result)
    assert total_volume == pytest.approx(208_000.0, rel=1e-6)


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_leftover_volume_fuses_touching_components_before_cutting_and_conserves_volume():
    """Two components placed FLUSH against each other (touching, zero-measure shared face, NOT
    overlapping) -- the exact non-self-interference case the sourced OCCT caveat warns about for a raw
    Compound cut argument (build-plan/research03aug/regions/purpose_tagged_regions_research.md). Both
    are 20x80x40mm boxes; `left` spans x in [-40,-20], `right` spans x in [-20,0] -- coincident at
    x=-20, disjoint everywhere else.

    Hand-computed: cavity 100x80x40 = 320,000 mm^3; the two components fused = 2 * (20*80*40) =
    128,000 mm^3 (they don't overlap, so fusing doesn't lose any volume to double-counting); leftover =
    320,000 - 128,000 = 192,000 mm^3."""
    import build123d as bd

    from packages.subsystems.regions import leftover_volume

    cavity = bd.Box(100.0, 80.0, 40.0)
    left = bd.Pos(-30.0, 0.0, 0.0) * bd.Box(20.0, 80.0, 40.0)
    right = bd.Pos(-10.0, 0.0, 0.0) * bd.Box(20.0, 80.0, 40.0)
    result = leftover_volume(cavity, [left, right])

    total_volume = sum(s.volume for s in result)
    assert total_volume == pytest.approx(192_000.0, rel=1e-6)

    labels = [s.label for s in result]
    assert labels == [f"leftover_{i}" for i in range(len(result))]
    assert len(set(labels)) == len(labels)  # every disjoint chunk gets its own distinct label


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_leftover_volume_custom_label_fn():
    import build123d as bd

    from packages.subsystems.regions import leftover_volume

    cavity = bd.Box(50.0, 50.0, 50.0)
    comp = bd.Pos(-10.0, 0.0, 0.0) * bd.Box(20.0, 50.0, 50.0)
    result = leftover_volume(cavity, [comp], label_fn=lambda i, s: f"custom_{i}")
    assert result
    assert all(s.label.startswith("custom_") for s in result)


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_leftover_volume_component_fully_spanning_the_cavity_leaves_nothing():
    """A component that fully occupies the cavity leaves zero leftover volume -- the degenerate/empty-
    result end of the range, opposite the "no components" test above."""
    import build123d as bd

    from packages.subsystems.regions import leftover_volume

    cavity = bd.Box(40.0, 40.0, 40.0)
    comp = bd.Box(40.0, 40.0, 40.0)
    result = leftover_volume(cavity, [comp])
    total_volume = sum(s.volume for s in result)
    assert total_volume == pytest.approx(0.0, abs=1e-6)
