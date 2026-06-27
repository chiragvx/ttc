"""Authoritative cross-process determinism gate.

(Was a strict-xfail anchor; now REAL and green — STEP B-rep canonicalization is implemented.)

Renders the canonical 4.5 mm pin in 3 fresh subprocesses and asserts BOTH the canonical mesh hash and
the canonical STEP B-rep hash are identical across all of them. Cross-process is what replay /
time-travel actually depends on (existential risk #3 — replaying a non-deterministic producer is the
event-sourcing anti-pattern). A drifted hash is SIGNAL — never silence it by loosening a tolerance.

Scope still open (tracked in build-plan/findings): single OS/arch (Windows here; the Linux fingerprint
is compared via `make ci-determinism`), and trivial geometry (no booleans/fillets — that couples to
Spike 1, where the topological-naming problem bites). Within this scope, OCCT 7.8.1 is reproducible.
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


def _probe(dia: str = "4.5") -> dict[str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "packages.truth_plane.regen.probe", dia],
        cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_pin_mesh_and_brep_identical_across_processes():
    runs = [_probe("4.5") for _ in range(3)]
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


@pytest.mark.skipif(not _HAS_KERNEL, reason="build123d/OCCT not installed (Linux dev container)")
def test_pin_brep_matches_golden_cross_platform_hash():
    from packages.truth_plane.regen.canonical import brep_sha256_from_step
    from packages.truth_plane.regen.generator import export_step_text, render_canonical_pin

    got = brep_sha256_from_step(export_step_text(render_canonical_pin(4.5)))
    assert got == GOLDEN_PIN_BREP_SHA256, (
        f"B-rep hash drifted: {got} != golden {GOLDEN_PIN_BREP_SHA256}. Real geometry change or "
        "toolchain change — investigate and rebaseline with sign-off, do not edit the constant blindly."
    )
