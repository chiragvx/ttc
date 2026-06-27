"""gmsh meshing for FEA — a STEP solid -> 2nd-order tetrahedral mesh + geometric face selection.

We use 2nd-order tets (10-node, CalculiX C3D10) because linear tets (C3D4) are far too stiff in
bending — the factor-of-safety on exactly the cantilever/bracket load cases we care about would be
badly wrong. Faces for boundary conditions are selected geometrically (e.g. the min-x face = clamped,
the max-x face = loaded) via gmsh bounding boxes, so no manual tagging is needed (the "hands-off"
requirement of Spike 4).

This module returns plain mesh data (nodes, C3D10 elements, node-id sets per selected face). The
CalculiX deck is generated in calculix.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import gmsh

# gmsh element type id for a 10-node (2nd-order) tetrahedron.
_TET10 = 11


@dataclass
class Mesh:
    nodes: dict[int, tuple[float, float, float]]
    tets10: list[tuple[int, ...]]          # each: 10 node ids (gmsh ordering)
    face_nodes: dict[str, set[int]]        # selector name -> node ids on that face
    char_len: float

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    @property
    def n_elements(self) -> int:
        return len(self.tets10)


def _axis_extreme_surface(axis: int, want_max: bool) -> int:
    """Return the surface tag whose centre is the extreme along `axis` (0=x,1=y,2=z)."""
    best_tag, best_val = None, None
    for dim, tag in gmsh.model.getEntities(2):
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(dim, tag)
        centre = ((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2)[axis]
        if best_val is None or (centre > best_val if want_max else centre < best_val):
            best_tag, best_val = tag, centre
    return best_tag


def _surface_node_ids(surf_tag: int) -> set[int]:
    tags, _, _ = gmsh.model.mesh.getNodes(2, surf_tag, includeBoundary=True)
    return {int(t) for t in tags}


def mesh_step(
    step_path: str,
    char_len: float,
    face_selectors: dict[str, tuple[int, bool]],
) -> Mesh:
    """Mesh a STEP file at characteristic length `char_len`. `face_selectors` maps a name to
    (axis, want_max), e.g. {"fixed": (0, False), "load": (0, True)} for clamp min-x / load max-x.
    Fully hands-off: no manual mesh interaction."""
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(step_path)
        gmsh.option.setNumber("Mesh.MeshSizeMax", char_len)
        gmsh.option.setNumber("Mesh.MeshSizeMin", char_len * 0.3)
        gmsh.model.mesh.generate(3)
        gmsh.model.mesh.setOrder(2)

        face_tags = {name: _axis_extreme_surface(ax, mx) for name, (ax, mx) in face_selectors.items()}

        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        nodes = {
            int(t): (coords[3 * i], coords[3 * i + 1], coords[3 * i + 2])
            for i, t in enumerate(node_tags)
        }

        elem_tags, elem_nodes = gmsh.model.mesh.getElementsByType(_TET10)
        tets10 = [tuple(int(n) for n in elem_nodes[10 * i:10 * i + 10]) for i in range(len(elem_tags))]

        face_nodes = {name: _surface_node_ids(tag) for name, tag in face_tags.items()}
        return Mesh(nodes=nodes, tets10=tets10, face_nodes=face_nodes, char_len=char_len)
    finally:
        gmsh.finalize()
