"""Determinism probe CLI.

Run as a fresh process so we measure CROSS-PROCESS reproducibility (the failure mode the Linux
fingerprint concern is really about — threading, allocator, session-counter, and library
nondeterminism that in-process repetition can mask):

    python -m packages.truth_plane.regen.probe <shape> [dia_mm]

`<shape>` is one of "pin" (default; the original trivial single-body probe — `dia_mm` optional, default
4.5), "bracket" (a real boolean cut, `render_canonical_boolean_cut`), or "wing" (a real loft,
`render_canonical_loft`) — see generator.py's module docstring for what each exercises and why.

Backward compatible with the pre-2026-07-21 CLI, which took a bare `dia_mm` with no shape argument
(`python -m packages.truth_plane.regen.probe 4.5`, still used by the Makefile / CI / docker README —
not this file's concern to update): if the first argument isn't a known shape name, it's parsed as the
pin's `dia_mm` instead, exactly as before.

Prints one JSON line: the canonical MESH hash and the canonical STEP B-REP hash of the rendered shape.
Spawn it N times per shape and compare.
"""

from __future__ import annotations

import json
import sys

from packages.truth_plane.regen.canonical import brep_sha256_from_step, mesh_sha256
from packages.truth_plane.regen.generator import (
    export_step_text,
    render_canonical_boolean_cut,
    render_canonical_loft,
    render_canonical_pin,
)


def _hashes(shape) -> dict[str, str]:
    return {
        "mesh": mesh_sha256(shape),
        "brep": brep_sha256_from_step(export_step_text(shape)),
    }


def probe(dia_mm: float = 4.5) -> dict[str, str]:
    """The original trivial pin probe. Kept as its own entry point (not folded behind the generic
    dispatcher) so existing callers importing `probe()` directly are unaffected."""
    return _hashes(render_canonical_pin(dia_mm=dia_mm))


def probe_boolean_cut() -> dict[str, str]:
    return _hashes(render_canonical_boolean_cut())


def probe_loft() -> dict[str, str]:
    return _hashes(render_canonical_loft())


_SHAPES = {
    "pin": lambda rest: probe(float(rest[0]) if rest else 4.5),
    "bracket": lambda rest: probe_boolean_cut(),
    "wing": lambda rest: probe_loft(),
}


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] not in _SHAPES:
        # Backward compatibility: the pre-2026-07-21 CLI took a bare dia_mm for the pin, no shape
        # argument (see module docstring) — still what the Makefile/CI/docker README invoke.
        try:
            dia = float(argv[1])
        except ValueError:
            raise SystemExit(f"unknown shape {argv[1]!r}; expected one of {sorted(_SHAPES)}")
        print(json.dumps(probe(dia), sort_keys=True))
        return 0
    shape = argv[1] if len(argv) > 1 else "pin"
    print(json.dumps(_SHAPES[shape](argv[2:]), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
