"""Spike 1 fallback #1: generator-deterministic tags survive regen & parameter changes (container)."""

from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.needs_kernel

_HAS_KERNEL = importlib.util.find_spec("build123d") is not None


def _brep(part):
    from packages.truth_plane.regen.canonical import brep_sha256_from_step
    from packages.truth_plane.regen.generator import export_step_text
    return brep_sha256_from_step(export_step_text(part.solid))


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_same_params_give_identical_tags_and_brep():
    from packages.truth_plane.regen.templated import render_bracket
    a = render_bracket(n_holes=4, hole_dia_mm=6.0)
    b = render_bracket(n_holes=4, hole_dia_mm=6.0)
    assert a.tags == b.tags
    assert _brep(a) == _brep(b)  # booleans included, still deterministic


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_param_change_keeps_tag_keys_but_changes_geometry():
    from packages.truth_plane.regen.templated import render_bracket
    a = render_bracket(n_holes=4, hole_dia_mm=6.0)
    b = render_bracket(n_holes=4, hole_dia_mm=8.0)
    assert a.tag_keys == b.tag_keys          # semantic identity stable across a parameter change
    assert _brep(a) != _brep(b)              # geometry actually changed


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_hole_count_changes_tags_deterministically():
    from packages.truth_plane.regen.templated import render_bracket
    assert render_bracket(n_holes=2).tag_keys == {"plate.body", "hole[0].bore", "hole[1].bore"}
    three = render_bracket(n_holes=3).tag_keys
    assert "hole[2].bore" in three and len(three) == 4
