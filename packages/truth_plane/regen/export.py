"""Neutral CAD interchange export — closes the "only Generate-G-Code" gap.

STEP carries the exact B-rep (the cross-platform-reproducible identity; the right hand-off to CAM/QA);
STL carries a mesh for printing/preview. Both are written deterministically by build123d/OCCT.
"""

from __future__ import annotations

import build123d as bd


def export_part(solid, file_path: str) -> str:
    """Export a build123d solid to STEP (.step/.stp) or STL (.stl), inferred from the extension."""
    ext = file_path.lower().rsplit(".", 1)[-1]
    if ext in ("step", "stp"):
        bd.export_step(solid, file_path)
    elif ext == "stl":
        bd.export_stl(solid, file_path)
    else:
        raise ValueError(f"unsupported export format '.{ext}' (use .step or .stl)")
    return file_path
