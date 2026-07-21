"""Authoritative cross-process determinism gate.

(Was a strict-xfail anchor; now REAL and green — STEP B-rep canonicalization is implemented.)

Renders each canonical probe shape in 3 fresh subprocesses and asserts BOTH the canonical mesh hash
and the canonical STEP B-rep hash are identical across all of them. Cross-process is what replay /
time-travel actually depends on (existential risk #3 — replaying a non-deterministic producer is the
event-sourcing anti-pattern). A drifted hash is SIGNAL — never silence it by loosening a tolerance.

Coverage (2026-07-21 audit fix): this used to hash ONLY the trivial canonical pin (a bare
`bd.Cylinder(...)`, no booleans/fillets/lofts) — an honest scope disclosure at the time, but one that
went stale once the generator grew real production paths that exercise operations a bare cylinder
never touches. Now covers THREE shapes (see `packages/truth_plane/regen/generator.py`'s module
docstring for what each exercises and why it was chosen):

  * the pin — `render_canonical_pin`, trivial, single body, no booleans/fillets/lofts.
  * a boolean cut — `render_canonical_boolean_cut`, reusing `templated.render_bracket`'s own defaults
    (the literal generator behind `demo_pipeline.run_hero_pipeline`, this project's flagship
    end-to-end slice): a real `part - bd.Cylinder(...)` face-splitting boolean.
  * a loft — `render_canonical_loft`, reusing `packages.subsystems.naca_wing`'s own registered
    defaults through the real `Subsystem.build(Namespace)` path: a real `bd.loft()` across multiple
    profile stations, the OCCT operation most exposed to spline-fitting/triangulation nondeterminism.

Scope still open (tracked in build-plan/findings): single OS/arch (Windows here; the Linux fingerprint
is compared via `make ci-determinism`). Persistent topological identity itself (OCAF/TNaming, mapping
a tag to the exact post-boolean OCCT face) is NOT covered here and still couples to Spike 1 — this
probe only checks that re-rendering the SAME shape produces byte-identical geometry, not that a face
tag survives a parameter change. Within this scope, OCCT 7.8.1 is reproducible for all three shapes
(verified directly by this file's own tests — see each shape's golden-hash test below).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.needs_kernel

_HAS_KERNEL = importlib.util.find_spec("build123d") is not None
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _probe(shape: str = "pin", *extra: str) -> dict[str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "packages.truth_plane.regen.probe", shape, *extra],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_pin_mesh_and_brep_identical_across_processes():
    runs = [_probe("pin", "4.5") for _ in range(3)]
    mesh_hashes = {r["mesh"] for r in runs}
    brep_hashes = {r["brep"] for r in runs}
    assert len(mesh_hashes) == 1, f"mesh non-deterministic across processes: {mesh_hashes}"
    assert len(brep_hashes) == 1, f"brep non-deterministic across processes: {brep_hashes}"


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_bracket_mesh_and_brep_identical_across_processes():
    """Same cross-process gate as the pin, but for a real BOOLEAN CUT shape (a bracket with bolt
    holes) — the face-splitting case the pin never exercised."""
    runs = [_probe("bracket") for _ in range(3)]
    mesh_hashes = {r["mesh"] for r in runs}
    brep_hashes = {r["brep"] for r in runs}
    assert len(mesh_hashes) == 1, f"mesh non-deterministic across processes: {mesh_hashes}"
    assert len(brep_hashes) == 1, f"brep non-deterministic across processes: {brep_hashes}"


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_wing_mesh_and_brep_identical_across_processes():
    """Same cross-process gate as the pin, but for a real LOFT shape (a NACA wing panel) — the
    spline-fitting/triangulation case the pin never exercised."""
    runs = [_probe("wing") for _ in range(3)]
    mesh_hashes = {r["mesh"] for r in runs}
    brep_hashes = {r["brep"] for r in runs}
    assert len(mesh_hashes) == 1, f"mesh non-deterministic across processes: {mesh_hashes}"
    assert len(brep_hashes) == 1, f"brep non-deterministic across processes: {brep_hashes}"


# Golden CROSS-PLATFORM B-rep hash for the canonical 4.5 mm pin under the pinned toolchain
# (build123d 0.10.0 / OCCT 7.8.1.1). VERIFIED IDENTICAL on Windows-x64 AND Linux-x64 (2026-06-27) —
# see build-plan/findings/2026-06-27-cross-platform-determinism.md. A mismatch means either a real
# geometry change OR a toolchain change: investigate and rebaseline WITH SIGN-OFF. Do NOT edit this
# constant to silence a failure. (NOTE: the MESH tessellation is platform-scoped and is deliberately
# NOT goldened here — only the exact B-rep is cross-platform stable. arm64 unverified.)
GOLDEN_PIN_BREP_SHA256 = "4eb40ae2d0e7d4b9132f253a094ef627ddf2814a408101c07f0fae76217a28b3"

# Golden B-rep hash for the canonical boolean-cut bracket (`render_canonical_boolean_cut`,
# `render_bracket`'s own defaults) — established directly on THIS run (Windows-x64, build123d 0.10.0 /
# OCCT 7.8.1.1), same method as the pin's golden hash above. UNLIKE the pin's, this has NOT been
# independently verified cross-platform (Linux) yet — the pin's cross-platform equality was a separate,
# explicitly-checked event (2026-06-27, see build-plan/findings/2026-06-27-cross-platform-determinism.md)
# BEFORE it was hard-pinned as "verified identical"; this constant skipped that step (Docker Desktop's
# daemon was unavailable in the sandbox this was authored in, and CLAUDE.md's numerical-determinism
# scope is a named human-wall item, not something to self-certify by guessing). This IS exercised on
# Linux already: `.github/workflows/ci.yml`'s `kernel` job runs `python -m pytest -q -ra` UNFILTERED
# inside the Linux docker image (ci.yml:44), which includes this exact assertion. A boolean cut is
# less exposed to cross-platform float/triangulation drift than a loft (see the wing's golden below),
# but still unverified — if Linux CI red-flags this specific test, that is the expected, honest first
# signal of a real (or at least unconfirmed) cross-platform gap, NOT evidence this probe extension is
# broken; investigate and rebaseline WITH SIGN-OFF, do not edit the constant to silence a failure, and
# do not weaken/skip the test to dodge it either.
GOLDEN_BRACKET_BREP_SHA256 = "8cfa0c3d5d97e8505b6fc74fccca3c3be6cc13de45d772a33e8d293c94132a4b"

# Golden B-rep hash for the canonical loft wing (`render_canonical_loft`, `naca_wing`'s own registered
# defaults) — established directly on THIS run (Windows-x64, build123d 0.10.0 / OCCT 7.8.1.1), same
# method as the pin's golden hash above and the SAME "not yet cross-platform verified" caveat as
# GOLDEN_BRACKET_BREP_SHA256 above applies here too (also exercised unfiltered by ci.yml's `kernel`
# job on Linux). A loft is the single OCCT operation most exposed to spline-fitting/triangulation
# nondeterminism of the three shapes this file now covers — of the two new goldens, THIS is the one
# most likely to legitimately differ cross-platform; a Linux CI failure here is a real, actionable
# finding to investigate and rebaseline WITH SIGN-OFF, not a bug in this probe extension. Do NOT edit
# this constant to silence a failure, and do not weaken/skip the test to dodge it either.
GOLDEN_WING_BREP_SHA256 = "ca5e4af6a24c3e964542a8cc46ba3824e1043884c7b0ec63024d206024316d80"


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_pin_brep_matches_golden_cross_platform_hash():
    from packages.truth_plane.regen.canonical import brep_sha256_from_step
    from packages.truth_plane.regen.generator import export_step_text, render_canonical_pin

    got = brep_sha256_from_step(export_step_text(render_canonical_pin(4.5)))
    assert got == GOLDEN_PIN_BREP_SHA256, (
        f"B-rep hash drifted: {got} != golden {GOLDEN_PIN_BREP_SHA256}. Real geometry change or "
        "toolchain change — investigate and rebaseline with sign-off, do not edit the constant blindly."
    )


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_bracket_brep_matches_golden_hash():
    from packages.truth_plane.regen.canonical import brep_sha256_from_step
    from packages.truth_plane.regen.generator import export_step_text, render_canonical_boolean_cut

    got = brep_sha256_from_step(export_step_text(render_canonical_boolean_cut()))
    assert got == GOLDEN_BRACKET_BREP_SHA256, (
        f"B-rep hash drifted: {got} != golden {GOLDEN_BRACKET_BREP_SHA256}. Real geometry change or "
        "toolchain change — investigate and rebaseline with sign-off, do not edit the constant blindly."
    )


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_wing_brep_matches_golden_hash():
    from packages.truth_plane.regen.canonical import brep_sha256_from_step
    from packages.truth_plane.regen.generator import export_step_text, render_canonical_loft

    got = brep_sha256_from_step(export_step_text(render_canonical_loft()))
    assert got == GOLDEN_WING_BREP_SHA256, (
        f"B-rep hash drifted: {got} != golden {GOLDEN_WING_BREP_SHA256}. Real geometry change or "
        "toolchain change — investigate and rebaseline with sign-off, do not edit the constant blindly."
    )
