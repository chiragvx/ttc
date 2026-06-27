"""Determinism probe CLI.

Run as a fresh process so we measure CROSS-PROCESS reproducibility (the failure mode the Linux
fingerprint concern is really about — threading, allocator, session-counter, and library
nondeterminism that in-process repetition can mask):

    python -m packages.truth_plane.regen.probe [dia_mm]

Prints one JSON line: the canonical MESH hash and the canonical STEP B-REP hash of the rendered pin.
Spawn it N times and compare.
"""

from __future__ import annotations

import json
import sys

from packages.truth_plane.regen.canonical import brep_sha256_from_step, mesh_sha256
from packages.truth_plane.regen.generator import export_step_text, render_canonical_pin


def probe(dia_mm: float = 4.5) -> dict[str, str]:
    pin = render_canonical_pin(dia_mm=dia_mm)
    return {
        "mesh": mesh_sha256(pin),
        "brep": brep_sha256_from_step(export_step_text(pin)),
    }


def main(argv: list[str]) -> int:
    dia = float(argv[1]) if len(argv) > 1 else 4.5
    print(json.dumps(probe(dia), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
