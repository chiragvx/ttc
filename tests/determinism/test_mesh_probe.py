"""In-process determinism sanity checks.

The cross-process REPRODUCIBILITY gate lives in test_mesh_determinism.py. Here we assert the
complementary properties that make a green gate meaningful:
  * the hashes are change-SENSITIVE (a different diameter -> different mesh AND brep hashes), so
    "stable" cannot be confused with "constant" / over-rounded;
  * mesh and brep are distinct hashes (they hash different representations);
  * the probe is stable when called twice in one process.
"""

from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.needs_kernel

_HAS_KERNEL = importlib.util.find_spec("build123d") is not None


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_mesh_and_brep_change_sensitive():
    from packages.truth_plane.regen.canonical import brep_sha256_from_step, mesh_sha256
    from packages.truth_plane.regen.generator import export_step_text, render_canonical_pin

    p45 = render_canonical_pin(4.5)
    p50 = render_canonical_pin(5.0)
    assert mesh_sha256(p45) != mesh_sha256(p50), "mesh hash insensitive to a real geometry change"
    assert brep_sha256_from_step(export_step_text(p45)) != brep_sha256_from_step(export_step_text(p50)), \
        "brep hash insensitive to a real geometry change"


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_mesh_and_brep_are_distinct():
    from packages.truth_plane.regen.probe import probe

    out = probe(4.5)
    assert out["mesh"] != out["brep"]


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_probe_stable_in_process():
    from packages.truth_plane.regen.probe import probe

    assert probe(4.5) == probe(4.5)
