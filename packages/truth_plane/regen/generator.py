"""Minimal deterministic geometry generator (Phase 0 probe scope).

This is NOT the templated production generator (that comes after Spike 1 proves persistent
topological identity). It exists only to give the determinism probe a real, kernel-backed solid to
hash. Keep it tiny and parameter-driven — no booleans/fillets yet (those are exactly where the
identity problem bites; out of scope for the determinism probe).
"""

from __future__ import annotations

import os
import tempfile

import build123d as bd


def render_canonical_pin(dia_mm: float = 4.5, length_mm: float = 20.0):
    """A simple cylindrical pin. Returns a build123d Solid."""
    return bd.Cylinder(radius=dia_mm / 2.0, height=length_mm).solid()


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
