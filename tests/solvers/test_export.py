"""Neutral CAD export: STEP + STL files are produced and well-formed (container)."""

from __future__ import annotations

import importlib.util
import os

import pytest

pytestmark = pytest.mark.needs_kernel

_HAS_KERNEL = importlib.util.find_spec("build123d") is not None


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_step_and_stl_export(tmp_path):
    from packages.truth_plane.regen.export import export_part
    from packages.truth_plane.regen.generator import render_canonical_pin

    pin = render_canonical_pin(4.5)

    step = export_part(pin, str(tmp_path / "pin.step"))
    assert os.path.getsize(step) > 0
    assert open(step, encoding="utf-8").read(13).startswith("ISO-10303-21")

    stl = export_part(pin, str(tmp_path / "pin.stl"))
    assert os.path.getsize(stl) > 0


@pytest.mark.skipif(not _HAS_KERNEL, reason="needs build123d (Linux container)")
def test_unsupported_format_rejected(tmp_path):
    from packages.truth_plane.regen.export import export_part
    from packages.truth_plane.regen.generator import render_canonical_pin
    with pytest.raises(ValueError):
        export_part(render_canonical_pin(4.5), str(tmp_path / "pin.obj"))
