"""Meshing-robustness sweep — Spike 4 kill-criterion #1 (auto-mesh fails on > 15% of a geometry set).

Runs a varied set of solids (boxes, cylinders, L-brackets, slotted plates, holed brackets) through the
hands-off mesher and records the auto-mesh success rate. "Success" = meshes without exception, yields
elements, and both BC faces are selectable — i.e. fully hands-off.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

import build123d as bd

from packages.truth_plane.regen.generator import export_step_text
from packages.truth_plane.regen.templated import render_bracket
from packages.truth_plane.solvers.mesh import mesh_step

_FACES = {"fixed": (0, False), "load": (0, True)}


@dataclass
class GeoResult:
    name: str
    ok: bool
    n_nodes: int = 0
    n_elements: int = 0
    error: str = ""


def _l_bracket(arm: float, height: float, t: float, w: float = 20.0):
    # both arms anchored at the x=0,z=0 corner so they overlap there and FUSE into one solid
    horiz = bd.Pos(arm / 2, 0, t / 2) * bd.Box(arm, w, t)
    vert = bd.Pos(t / 2, 0, height / 2) * bd.Box(t, w, height)
    fused = horiz + vert
    return fused.solids().sort_by(lambda s: s.volume)[-1] if len(fused.solids()) > 1 else fused.solid()


def _slotted_plate(width: float, depth: float, t: float):
    plate = bd.Box(width, depth, t)
    slot = bd.Pos(0, 0, 0) * bd.Box(width * 0.5, depth * 0.25, t * 2)
    return (plate - slot).solid()


def geometries() -> list[tuple[str, object]]:
    g: list[tuple[str, object]] = []
    for (lx, w, h) in [(100, 10, 10), (50, 50, 5), (80, 20, 10), (30, 30, 30), (120, 15, 8), (60, 40, 3)]:
        g.append((f"box_{lx}x{w}x{h}", bd.Box(lx, w, h).solid()))
    for (r, h) in [(10, 40), (5, 60), (20, 20), (8, 80)]:
        g.append((f"cyl_r{r}_h{h}", bd.Cylinder(radius=r, height=h).solid()))
    for (a, b, t) in [(50, 40, 5), (60, 30, 6), (40, 40, 4)]:
        g.append((f"L_{a}x{b}x{t}", _l_bracket(a, b, t)))
    for (wd, dp, t) in [(60, 40, 5), (80, 30, 6)]:
        g.append((f"slot_{wd}x{dp}", _slotted_plate(wd, dp, t)))
    for n in [2, 3, 4, 6]:
        g.append((f"bracket_{n}holes", render_bracket(n_holes=n).solid))
    return g


def run_sweep(char_len: float = 5.0) -> list[GeoResult]:
    results: list[GeoResult] = []
    for name, solid in geometries():
        fd, path = tempfile.mkstemp(suffix=".step")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(export_step_text(solid))
            m = mesh_step(path, char_len=char_len, face_selectors=_FACES)
            ok = m.n_elements > 0 and all(m.face_nodes.values())
            results.append(GeoResult(name, ok, m.n_nodes, m.n_elements))
        except Exception as e:  # noqa: BLE001 - we WANT to record any mesh failure
            results.append(GeoResult(name, False, error=f"{type(e).__name__}: {e}"))
        finally:
            os.remove(path)
    return results


def success_rate(results: list[GeoResult]) -> float:
    return sum(1 for r in results if r.ok) / len(results) if results else 0.0
