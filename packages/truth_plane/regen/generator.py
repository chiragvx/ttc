"""Minimal deterministic geometry generator (Phase 0 probe scope).

This is NOT the templated production generator (that comes after Spike 1 proves persistent
topological identity). It exists only to give the determinism probe real, kernel-backed solids to
hash — kept tiny and parameter-driven.

Coverage (2026-07-21 audit fix): the original scope here was a single bare `bd.Cylinder(...)` — no
booleans, no lofts. That undersold what the determinism gate actually needed to watch, because the
production generator (`packages/truth_plane/regen/templated.py`) and the loft-based subsystem family
(`packages/subsystems/naca_wing.py` and siblings) both went live since and both exercise operations a
bare cylinder never touches:

  * `render_canonical_pin` — the original trivial single-body probe. Unchanged.
  * `render_canonical_boolean_cut` — a real `part - bd.Cylinder(...)` boolean, reusing
    `templated.render_bracket` (its own defaults — this is the literal generator behind
    `packages/truth_plane/demo_pipeline.py::run_hero_pipeline`, this project's flagship end-to-end
    slice, not a corner case) instead of reimplementing a parallel boolean here.
  * `render_canonical_loft` — a real `bd.loft(...)` across multiple profile stations, reusing
    `packages.subsystems.naca_wing`'s own registered ParamSpec defaults (via the same `Subsystem`/
    `Namespace` machinery every subsystem's own build goes through) instead of a standalone stand-in.

Both new probes call into the REAL production code paths (not simplified reimplementations), so a
drifted hash here means the actual generator/subsystem code is non-deterministic, not a probe-only
toy. This still does not touch OCAF/TNaming (persistent topological identity, CLAUDE.md's named
human-wall item) — it is a cheap, mechanical, cross-process hash comparison over more shapes, nothing
more.
"""

from __future__ import annotations

import os
import tempfile

import build123d as bd


def render_canonical_pin(dia_mm: float = 4.5, length_mm: float = 20.0):
    """A simple cylindrical pin — no booleans, no lofts. Returns a build123d Solid."""
    return bd.Cylinder(radius=dia_mm / 2.0, height=length_mm).solid()


def render_canonical_boolean_cut():
    """A small mounting bracket: `templated.render_bracket`'s own defaults (a plate with a row of
    bolt holes cut via `part - bd.Cylinder(...)`) — the exact face-splitting boolean shape templated.py's
    own module docstring names as the positional-identity hazard, and the literal geometry behind
    `demo_pipeline.run_hero_pipeline`. Returns a build123d Solid (the `TaggedPart.solid`)."""
    from packages.truth_plane.regen.templated import render_bracket

    return render_bracket().solid


def render_canonical_loft():
    """A small NACA 4-digit lofted wing panel: `packages.subsystems.naca_wing`'s own registered
    ParamSpec defaults, built through the same `Subsystem.build(Namespace)` call every real subsystem
    goes through (not a reimplemented stand-in loft). Exercises `bd.loft()` across 3 profile stations
    — lofts are typically the OCCT operation most exposed to spline-fitting/triangulation
    nondeterminism, and were completely unhashed before this. Returns a build123d Solid (the
    `TaggedPart.solid`)."""
    from packages.subsystems import get_subsystem_model
    from packages.subsystems.base import Namespace

    naca_wing = get_subsystem_model("naca_wing")
    ns = Namespace(naca_wing.defaults())
    return naca_wing.build(ns).solid


def export_step_text(shape) -> str:
    """Export a shape to STEP and return the raw text (pre-canonicalization)."""
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        exporter = getattr(bd, "export_step", None)
        if exporter is not None:
            exporter(shape, path)
        else:  # pragma: no cover - API fallback
            shape.export_step(path)
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    finally:
        os.remove(path)
