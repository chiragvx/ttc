"""CalculiX (ccx) linear-static driver: build a deck from a Mesh, solve, parse displacement + stress.

The Validator is a ROUTER, not an LLM: this code turns solver output into numbers; an LLM never
originates a stress/FS value.

Two FEA correctness details that, if wrong, give plausible-but-wrong numbers (so they are validated
against a closed-form case in the tests, never self-certified):
  * C3D10 node ordering — gmsh's 10-node tet differs from CalculiX's in the last two mid-edge nodes;
    we apply the meshio permutation [0,1,2,3,4,5,6,7,9,8].
  * a clamped face is a stress singularity — peak von Mises does NOT converge; tip deflection does,
    so deflection is the validation oracle.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from packages.truth_plane.solvers.mesh import Mesh

# gmsh tet10 -> CalculiX C3D10 mid-edge node permutation (swap last two).
_GMSH_TO_CCX_TET10 = (0, 1, 2, 3, 4, 5, 6, 7, 9, 8)


@dataclass
class SolveResult:
    max_disp_mag_mm: float
    tip_disp_z_mm: float           # mean -z deflection of the load face (signed magnitude)
    max_von_mises_mpa: float
    n_nodes: int
    n_elements: int


def _fmt_nset(name: str, ids) -> list[str]:
    out = [f"*NSET, NSET={name}"]
    ids = sorted(ids)
    for i in range(0, len(ids), 12):
        out.append(", ".join(str(n) for n in ids[i:i + 12]))
    return out


def write_deck(mesh: Mesh, *, youngs_mod_mpa: float, poisson: float, tip_load_n: float,
               fixed: str = "fixed", load: str = "load") -> str:
    lines: list[str] = ["*NODE"]
    for nid, (x, y, z) in mesh.nodes.items():
        lines.append(f"{nid}, {x:.9g}, {y:.9g}, {z:.9g}")

    lines.append("*ELEMENT, TYPE=C3D10, ELSET=EALL")
    for eid, nodes in enumerate(mesh.tets10, start=1):
        perm = [nodes[i] for i in _GMSH_TO_CCX_TET10]
        lines.append(f"{eid}, " + ", ".join(str(n) for n in perm))

    lines += _fmt_nset("NFIX", mesh.face_nodes[fixed])
    lines += _fmt_nset("NLOAD", mesh.face_nodes[load])

    lines += [
        "*MATERIAL, NAME=MAT",
        "*ELASTIC",
        f"{youngs_mod_mpa}, {poisson}",
        "*SOLID SECTION, ELSET=EALL, MATERIAL=MAT",
        "*STEP",
        "*STATIC",
        "*BOUNDARY",
        "NFIX, 1, 3",
        "*CLOAD",
        # distribute total tip load over the load-face nodes, in -z (lumped; tip deflection is
        # insensitive to the exact distribution by Saint-Venant)
        f"NLOAD, 3, {-tip_load_n / max(1, len(mesh.face_nodes[load])):.9g}",
        "*NODE FILE",
        "U",
        "*EL FILE",
        "S",
        "*END STEP",
    ]
    return "\n".join(lines) + "\n"


def _parse_frd(path: str) -> tuple[dict[int, tuple[float, float, float]], dict[int, float]]:
    """Return (displacements by node, von-Mises by node) from a CalculiX .frd."""
    disp: dict[int, tuple[float, float, float]] = {}
    vm: dict[int, float] = {}
    mode = None  # None | "DISP" | "STRESS"
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            tag = line[:3]
            if tag == " -4":
                mode = "DISP" if "DISP" in line else ("STRESS" if "STRESS" in line else None)
                continue
            if tag == " -3":
                mode = None
                continue
            if tag == " -1" and mode:
                nid = int(line[3:13])
                vals = []
                k = 13
                while k + 12 <= len(line.rstrip("\n")) and len(vals) < 6:
                    chunk = line[k:k + 12].strip()
                    if not chunk:
                        break
                    vals.append(float(chunk))
                    k += 12
                if mode == "DISP" and len(vals) >= 3:
                    disp[nid] = (vals[0], vals[1], vals[2])
                elif mode == "STRESS" and len(vals) >= 6:
                    sxx, syy, szz, sxy, syz, szx = vals[:6]
                    vm[nid] = math.sqrt(
                        0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
                        + 3.0 * (sxy ** 2 + syz ** 2 + szx ** 2)
                    )
    return disp, vm


def solve(mesh: Mesh, *, youngs_mod_mpa: float, poisson: float, tip_load_n: float,
          load: str = "load") -> SolveResult:
    ccx = shutil.which("ccx") or shutil.which("ccx_2.21") or "ccx"
    deck = write_deck(mesh, youngs_mod_mpa=youngs_mod_mpa, poisson=poisson, tip_load_n=tip_load_n)
    workdir = tempfile.mkdtemp(prefix="ccx_")
    job = os.path.join(workdir, "job")
    try:
        with open(job + ".inp", "w", encoding="utf-8") as fh:
            fh.write(deck)
        proc = subprocess.run([ccx, "job"], cwd=workdir, capture_output=True, text=True, timeout=600)
        frd = job + ".frd"
        if not os.path.exists(frd):
            raise RuntimeError(f"ccx produced no .frd (rc={proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-1000:]}")
        disp, vm = _parse_frd(frd)
        if not disp:
            raise RuntimeError("no displacements parsed from .frd")
        max_mag = max(math.sqrt(dx * dx + dy * dy + dz * dz) for dx, dy, dz in disp.values())
        load_ids = [n for n in mesh.face_nodes[load] if n in disp]
        tip_z = sum(disp[n][2] for n in load_ids) / max(1, len(load_ids))
        return SolveResult(
            max_disp_mag_mm=max_mag,
            tip_disp_z_mm=abs(tip_z),
            max_von_mises_mpa=max(vm.values()) if vm else float("nan"),
            n_nodes=mesh.n_nodes,
            n_elements=mesh.n_elements,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
