"""Canonical mesh hashing — the determinism primitive.

To detect whether the kernel reproduces identical geometry run-to-run, we hash a *canonical* form of
the tessellation that is invariant to mesh-ordering noise but sensitive to real geometric change:

  * round every vertex coordinate to `dp` decimals (guards last-bit float noise, not real drift);
  * represent each triangle as its 3 rounded vertices SORTED (winding/rotation-invariant);
  * sort the full triangle list (vertex/triangle emission-order-invariant);
  * sha256 the result.

A drifted hash means the kernel produced genuinely different geometry — that is SIGNAL. This is the
mesh half of the full determinism gate; the full gate (Linux CI) also canonicalizes the STEP B-rep
and stamps a pinned toolchain fingerprint.
"""

from __future__ import annotations

import hashlib
import re

# --- STEP B-rep canonicalization -------------------------------------------------------------
# OCCT's STEP export embeds two volatile fields that are NOT geometry:
#   * the FILE_NAME ISO-8601 timestamp (changes every export);
#   * a NEXT_ASSEMBLY_USAGE_OCCURRENCE id — an OCCT session counter (resets per fresh process, so it
#     is stable cross-process but increments within one process).
# We neutralize both so the hash reflects geometry, not wall-clock or session state. The authoritative
# determinism check runs CROSS-PROCESS (fresh interpreter) — that is what replay actually depends on.
_STEP_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_STEP_NAUO_ID_RE = re.compile(r"(NEXT_ASSEMBLY_USAGE_OCCURRENCE\(')[^']*'")


def canonical_step_text(text: str) -> str:
    text = _STEP_TIMESTAMP_RE.sub("TIMESTAMP", text)
    text = _STEP_NAUO_ID_RE.sub(r"\1ID'", text)
    return text


def brep_sha256_from_step(step_text: str) -> str:
    """sha256 of the canonicalized STEP B-rep text (geometry, not header/session noise)."""
    return hashlib.sha256(canonical_step_text(step_text).encode("utf-8")).hexdigest()


def _pt(v, dp: int) -> tuple[float, float, float]:
    # build123d Vector exposes .X/.Y/.Z; fall back to indexing if needed.
    try:
        return (round(v.X, dp), round(v.Y, dp), round(v.Z, dp))
    except AttributeError:  # pragma: no cover - defensive
        return (round(v[0], dp), round(v[1], dp), round(v[2], dp))


def canonical_mesh_bytes(verts, tris, dp: int = 6) -> bytes:
    pts = [_pt(v, dp) for v in verts]
    canon = [tuple(sorted((pts[a], pts[b], pts[c]))) for (a, b, c) in tris]
    canon.sort()
    return repr(canon).encode("utf-8")


def mesh_sha256(shape, tolerance: float = 0.05, dp: int = 6) -> str:
    """Canonical sha256 of a shape's tessellation at a fixed deflection tolerance."""
    verts, tris = shape.tessellate(tolerance)
    return hashlib.sha256(canonical_mesh_bytes(verts, tris, dp)).hexdigest()
