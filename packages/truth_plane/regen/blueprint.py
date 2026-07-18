"""Blueprint 3-view renderer (2026-07-19) — orthographic front/top/right line-silhouette views of the
whole assembly, one PNG, with per-part colours, view titles, and labelled XYZ direction axes.

Purpose (see the self-verifying build-loop harness the user scoped this session): give BOTH the user
AND a vision model a correct, unambiguous picture of what is currently built, so the model can judge
shape/position/part-count against the design scope. The axis labels + "looking -Y"-style view titles
exist specifically so a vision model can never misread orientation (the user's explicit requirement).

This is Tier-1/kernel work (it tessellates real build123d solids), NOT a Tier-0 hot-path call — it is
requested on demand (`GET /blueprint`) and, later, by the validation step, never on a slider drag.
matplotlib + build123d are imported LAZILY inside the render function so importing this module from a
pure-python path never drags in the kernel or a plotting backend.

PARTS STAY SEPARATE (the user's hard constraint this session): each instance is built, world-placed
(via the SAME `instance_world_offsets` + per-instance `Transform` the viewport's `render_assembly`
uses, so the blueprint matches the 3D view exactly), tessellated, and drawn in its OWN colour with its
instance id in the legend — never fused. A part that fails to build is skipped with a log line, same
defensive stance as `assembly.py` (one broken part must not blank the whole drawing)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from packages.subsystems import get_subsystem
from packages.subsystems.assembly import instance_world_offsets

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger

_logger = logging.getLogger(__name__)

# Deterministic, high-contrast palette cycled per instance (so the same design always colours the same
# way across re-renders in a validation loop). Blue matches the viewport's own part colour.
_PALETTE = [
    "#4a9eff", "#54c66b", "#e0a13a", "#c678dd", "#e06c75",
    "#56b6c2", "#d19a66", "#98c379", "#61afef", "#e5c07b",
]

# (title, horizontal-axis index, vertical-axis index, h-label, v-label). Standard engineering views;
# the parenthetical "looking <dir>" tells a vision model exactly which way the camera points.
_VIEWS = [
    ("FRONT  (looking down -Y)", 0, 2, "+X  (right)", "+Z  (up)"),
    ("TOP  (looking down -Z)",   0, 1, "+X  (right)", "+Y  (aft)"),
    ("RIGHT  (looking along +X)", 1, 2, "+Y  (aft)",  "+Z  (up)"),
]

_TESSELLATION_MM = 1.5  # coarse — a silhouette outline needs no fine facets, and this stays fast


def _placed_triangles(ledger: "MasterParametricLedger"):
    """Yield `(instance_id, subsystem_type, ndarray[n,3,3])` — each instance's world-placed geometry
    as triangle vertex coordinates. World placement replicates `assembly.render_assembly`: the
    instance's `instance_world_offsets` translation plus its own `Transform` rotation, so the blueprint
    is the SAME scene the viewport shows."""
    import build123d as bd
    import numpy as np

    offsets = instance_world_offsets(ledger)
    for iid, inst in ledger.instances.items():
        try:
            builder = get_subsystem(inst.subsystem_type).geometry_builder
            if builder is None:
                continue
            part = builder(ledger, iid)
            if part is None:
                continue
            solid = part.solid
            rx = ry = rz = 0.0
            if inst.transform is not None:
                rx, ry, rz = inst.transform.rx_deg, inst.transform.ry_deg, inst.transform.rz_deg
            if rx or ry or rz:
                solid = bd.Rotation(rx, ry, rz) * solid
            ox, oy, oz = offsets.get(iid, (0.0, 0.0, 0.0))
            solid = bd.Pos(ox, oy, oz) * solid
            verts, tris = solid.tessellate(_TESSELLATION_MM)
            if not tris:
                continue
            V = np.array([[v.X, v.Y, v.Z] for v in verts])
            T = np.array(tris)
            yield iid, inst.subsystem_type, V[T]
        except Exception:
            _logger.exception("blueprint: instance %s (%s) failed to build; skipping", iid, inst.subsystem_type)


def render_blueprint(ledger: "MasterParametricLedger", title: str = "Design blueprint") -> bytes:
    """Render the whole assembly as a 3-view orthographic blueprint PNG (bytes). Front / top / right
    silhouettes, one colour per instance, labelled XYZ axes + view titles + a legend of part ids.
    Returns a small 'nothing to draw yet' placeholder PNG for an empty file."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Patch
    import numpy as np

    parts = list(_placed_triangles(ledger))

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2), facecolor="#0d1117")
    if not parts:
        for ax in axes:
            ax.set_facecolor("#0d1117")
            ax.text(0.5, 0.5, "no parts yet", color="#6e7681", ha="center", va="center",
                    transform=ax.transAxes, fontsize=12, style="italic")
            ax.set_xticks([]); ax.set_yticks([])
            for s in ax.spines.values():
                s.set_color("#30363d")
    else:
        colours = {iid: _PALETTE[i % len(_PALETTE)] for i, (iid, _t, _T) in enumerate(parts)}
        for ax, (vtitle, hi, vi, hl, vl) in zip(axes, _VIEWS):
            ax.set_facecolor("#0d1117")
            for iid, _stype, T in parts:
                polys = [np.column_stack([tri[:, hi], tri[:, vi]]) for tri in T]
                ax.add_collection(PolyCollection(polys, facecolors=colours[iid],
                                                 edgecolors="none", alpha=0.85))
            ax.set_title(vtitle, color="#e6edf3", fontsize=11, pad=8)
            ax.set_xlabel(hl, color="#8b949e", fontsize=9)
            ax.set_ylabel(vl, color="#8b949e", fontsize=9)
            ax.tick_params(colors="#484f58", labelsize=7)
            ax.set_aspect("equal")
            ax.autoscale()
            ax.margins(0.08)
            ax.grid(True, color="#21262d", lw=0.5)
            for s in ax.spines.values():
                s.set_color("#30363d")
        # one shared legend of instance-id -> colour (parts are separate; the ids match the outliner)
        handles = [Patch(facecolor=colours[iid], edgecolor="none", label=f"{iid}  ({stype})")
                   for iid, stype, _T in parts]
        fig.legend(handles=handles, loc="lower center", ncol=min(len(handles), 4),
                   frameon=False, fontsize=8, labelcolor="#c9d1d9")

    fig.suptitle(title, color="#e6edf3", fontsize=13)
    fig.tight_layout(rect=[0, 0.06, 1, 0.95])

    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=90, facecolor="#0d1117")
    plt.close(fig)
    return buf.getvalue()
